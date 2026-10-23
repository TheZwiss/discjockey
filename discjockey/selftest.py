"""`Discjockey --self-test` (spec public-release §7): proves a build works, with no network and no library.
scripts/build_app.sh and the release workflow run it on the signed app; failing it fails the release.

It points DISCJOCKEY_SUPPORT at a scratch folder of its own (never the user's logins, settings or downloaded tools),
activates, then checks:
- every engine module and the bundled third-party packages import;
- ffmpeg, ffprobe and deno answer, and in the app they are the bundled ones (Contents/Resources/bin);
- a generated one-second tone converts to AIFF with the engine's own settings (audio.convert_to_aiff);
- the built UI (hub/static/index.html) is there with every file it loads;
- the built-in yt-dlp passes the update check in a process of its own (`--check-tools`), and tool_updates sees its
  version (proves the plain-file copy is found; phase 3 review).
- in the app, the licences folder (Contents/Resources/licenses) has INDEX.txt and every text it names.
Prints `FAIL <problem>` per problem and `self-test passed` at the end; exit 0 only when nothing failed."""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import discjockey
from . import tools

THIRD_PARTY = ("streamrip", "streamrip.client", "streamrip.config", "mutagen", "numpy", "certifi", "requests",
               "bottle", "webview", "webview.platforms.cocoa", "objc", "AppKit", "Foundation", "WebKit",
               tools.YT_DLP, tools.EJS)
PROGRAMS = {"ffmpeg": ["-version"], "ffprobe": ["-version"], "deno": ["--version"]}
MIN_MODULES = 30  # the engine has more than 40; fewer means the app was collected without them
TIMEOUT = 120  # seconds for one program run or the update check
ASSET = re.compile(r"""(?:src|href)=["'](?:\./)?(assets/[^"'?#]+)""")

Runner = Callable[..., subprocess.CompletedProcess]


def check_modules(package=discjockey) -> list[str]:
    problems, count = [], 0
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        count += 1
        try:
            importlib.import_module(info.name)
        except Exception as e:
            problems.append(f"import {info.name}: {type(e).__name__}: {e}")
    if count < MIN_MODULES:
        problems.append(f"only {count} engine modules found (expected at least {MIN_MODULES})")
    return problems


def check_imports(names: tuple[str, ...] = THIRD_PARTY) -> list[str]:
    problems = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:
            problems.append(f"import {name}: {type(e).__name__}: {e}")
    return problems


def check_programs(bin_dir: Path | None, run: Runner = subprocess.run) -> list[str]:
    """Each program is on PATH and answers its version flag; with `bin_dir` (the app) it must be the bundled copy."""
    problems = []
    for name, flag in PROGRAMS.items():
        found = shutil.which(name)
        if found is None:
            problems.append(f"{name}: not found on PATH")
            continue
        if bin_dir is not None and not tools.inside(Path(found), bin_dir):
            problems.append(f"{name}: {found} is not the bundled copy in {bin_dir}")
        try:
            r = run([found, *flag], capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            problems.append(f"{name}: {type(e).__name__}: {e}")
            continue
        first = (r.stdout or "").splitlines()[:1]
        if r.returncode != 0 or not first or name not in first[0]:
            said = (r.stdout or r.stderr or "").strip()[:200]
            problems.append(f"{name}: {' '.join([found, *flag])} answered {r.returncode}: {said}")
    return problems


def check_conversion(work: Path, run: Runner = subprocess.run) -> list[str]:
    """A one-second 440 Hz tone at 48 kHz (made by ffmpeg) becomes 16-bit 44.1 kHz AIFF through the engine's own
    convert_to_aiff, the call every download goes through."""
    from . import audio
    tone, out = work / "tone.flac", work / "tone.aiff"
    try:
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "flac", str(tone)],
            check=True, capture_output=True, timeout=TIMEOUT)
        audio.convert_to_aiff(tone, out, 1.0)
        r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate:format=duration",
                 "-of", "json", str(out)], check=True, capture_output=True, text=True, timeout=TIMEOUT)
        info = json.loads(r.stdout)
    except Exception as e:
        return [f"tone to AIFF: {type(e).__name__}: {e}"]
    stream = (info.get("streams") or [{}])[0]
    duration = float(info.get("format", {}).get("duration", 0))
    problems = []
    if stream.get("codec_name") != "pcm_s16be" or stream.get("sample_rate") != "44100":
        problems.append(f"tone to AIFF: got {stream.get('codec_name')} at {stream.get('sample_rate')} Hz")
    if abs(duration - 1.0) > 0.05:
        problems.append(f"tone to AIFF: {duration:.3f} s instead of 1 s")
    return problems


def check_ui(index: Path) -> list[str]:
    if not index.is_file():
        return [f"UI: {index} is missing"]
    assets = ASSET.findall(index.read_text(encoding="utf-8"))
    if not assets:
        return [f"UI: {index.name} loads no assets/ files"]
    return [f"UI: {index.parent / a} is missing" for a in assets if not (index.parent / a).is_file()]


def check_licenses(folder: Path) -> list[str]:
    """The app's licences folder (Settings links to it, spec public-release §6.5): INDEX.txt lists the bundled parts
    and every text it points to (`… -> file`, or `… -> folder/` for a folder with texts in it) is there."""
    index = folder / "INDEX.txt"
    if not index.is_file():
        return [f"licences: {index} is missing"]
    lines = [line for line in index.read_text(encoding="utf-8").splitlines()[1:] if line.strip()]
    if not lines:
        return [f"licences: {index} lists nothing"]
    named = [line.rsplit(" -> ", 1)[1].strip() for line in lines if " -> " in line]

    def problem(name: str) -> str | None:
        path = folder / name
        if name.endswith("/"):
            if not path.is_dir():
                return f"licences: {path} is missing"
            return None if any(path.iterdir()) else f"licences: {path} has no texts"
        return None if path.is_file() else f"licences: {path} is missing"

    return [found for found in map(problem, named) if found]


def check_download_tools(support: Path, work: Path, run: Runner = subprocess.run) -> list[str]:
    """A copy of the built-in yt-dlp and yt-dlp-ejs passes `--check-tools` in a process of its own, and
    tool_updates reports the built-in version."""
    from . import tool_updates
    builtin = tools.builtin_package(support)
    if builtin is None:
        return ["yt-dlp: no built-in copy found on sys.path"]
    candidate = work / "candidate"
    try:
        for name in (tools.YT_DLP, tools.EJS):
            shutil.copytree(builtin.parent / name, candidate / name, ignore=shutil.ignore_patterns("__pycache__"))
    except OSError as e:
        return [f"yt-dlp: could not copy the built-in copy next to {builtin}: {e}"]
    cmd, cwd = tools.check_command(candidate)
    try:
        r = run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return [f"--check-tools: {type(e).__name__}: {e}"]
    lines = (r.stdout or "").strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    problems = []
    if (r.returncode != 0 or not isinstance(answer, dict)
            or not all(isinstance(answer.get(k), str) for k in ("yt-dlp", "yt-dlp-ejs"))):
        problems.append(f"--check-tools failed ({r.returncode}): {(r.stderr or r.stdout or '').strip()[-300:]}")
    elif answer["yt-dlp"] != tools.package_version(builtin):
        problems.append(f"--check-tools found yt-dlp {answer['yt-dlp']}, "
                        f"the built-in copy is {tools.package_version(builtin)}")
    status = tool_updates.current_status(support)["yt-dlp"]
    if status["version"] is None or status["source"] != "built_in":
        problems.append(f"yt-dlp status: {status}")
    return problems


def run_checks(work: Path, support: Path, bin_dir: Path | None, frozen: bool,
               run: Runner = subprocess.run) -> list[str]:
    problems = ["the app has no Contents/Resources/bin"] if frozen and bin_dir is None else []
    problems += check_modules()
    problems += check_imports()
    problems += check_programs(bin_dir, run)
    problems += check_conversion(work, run)
    from .hub import app as hub_app  # only for STATIC; importing it starts nothing
    problems += check_ui(hub_app.STATIC)
    problems += check_download_tools(support, work, run)
    if frozen:
        problems += check_licenses(tools.licenses_dir())
    return problems


def main(args: list[str]) -> int:
    if args:
        print("usage: Discjockey --self-test", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="discjockey-self-test-") as tmp:
        support = Path(tmp) / "support"
        support.mkdir()
        os.environ["DISCJOCKEY_SUPPORT"] = str(support)  # never the user's support folder, logins or tools
        activation = tools.activate(support=support)
        problems = run_checks(Path(tmp), support, activation.bin_dir, tools.is_frozen())
    for line in problems:
        print(f"FAIL {line}")
    print("self-test passed" if not problems else f"self-test failed: {len(problems)} problem(s)")
    return 0 if not problems else 1
