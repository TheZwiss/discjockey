import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from discjockey import REPO, selftest
from tools_helpers import install_update

PROGRAMS_HERE = all(shutil.which(p) for p in ("ffmpeg", "ffprobe", "deno"))
SKIP_WHY = ("ffmpeg, ffprobe or deno is not on PATH, so this check is skipped here; on CI the frozen app's own "
            "--self-test is the real check")


def fake_programs(folder: Path, answers: dict[str, str]) -> Path:
    folder.mkdir(parents=True)
    for name, line in answers.items():
        p = folder / name
        p.write_text(f"#!/bin/sh\necho '{line}'\n")
        p.chmod(0o755)
    return folder


# --- the UI file ---

def test_ui_with_every_asset_passes(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-1.js").write_text("")
    (tmp_path / "assets" / "index-1.css").write_text("")
    (tmp_path / "index.html").write_text('<script src="./assets/index-1.js"></script>'
                                         '<link href="./assets/index-1.css">')
    assert selftest.check_ui(tmp_path / "index.html") == []


def test_ui_with_a_missing_asset_fails(tmp_path):
    (tmp_path / "index.html").write_text('<script src="./assets/gone.js"></script>')
    assert selftest.check_ui(tmp_path / "index.html") == [f"UI: {tmp_path / 'assets/gone.js'} is missing"]


def test_ui_without_index_or_assets_fails(tmp_path):
    assert "is missing" in selftest.check_ui(tmp_path / "index.html")[0]
    (tmp_path / "index.html").write_text("<p>no build</p>")
    assert selftest.check_ui(tmp_path / "index.html") == ["UI: index.html loads no assets/ files"]


def test_the_real_ui_build_passes():
    from discjockey.hub import app
    assert selftest.check_ui(app.STATIC) == []


# --- the programs ---

ANSWERS = {"ffmpeg": "ffmpeg version 9.0.2", "ffprobe": "ffprobe version 9.0.2", "deno": "deno 2.9.8 (stable)"}


def test_programs_in_the_bundled_folder_pass(tmp_path, monkeypatch):
    bin_dir = fake_programs(tmp_path / "bin", ANSWERS)
    monkeypatch.setenv("PATH", str(bin_dir))
    assert selftest.check_programs(bin_dir) == []


def test_a_program_outside_the_bundled_folder_fails(tmp_path, monkeypatch):
    found = fake_programs(tmp_path / "homebrew", ANSWERS)
    monkeypatch.setenv("PATH", str(found))
    problems = selftest.check_programs(tmp_path / "Discjockey.app" / "Contents" / "Resources" / "bin")
    assert len(problems) == 3 and all("is not the bundled copy" in p for p in problems)


def test_a_missing_or_silent_program_fails(tmp_path, monkeypatch):
    bin_dir = fake_programs(tmp_path / "bin", {"ffmpeg": "ffmpeg version 9", "ffprobe": "nonsense"})
    monkeypatch.setenv("PATH", str(bin_dir))
    problems = selftest.check_programs(None)
    assert problems[0].startswith("ffprobe: ") and problems[1] == "deno: not found on PATH"


# --- the engine's modules ---

def test_every_engine_module_imports():
    assert selftest.check_modules() == []


def test_a_broken_or_tiny_package_fails(tmp_path, monkeypatch):
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "good.py").write_text("")
    (pkg / "bad.py").write_text("raise ImportError('gone')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    import fakepkg
    problems = selftest.check_modules(fakepkg)
    assert problems == ["import fakepkg.bad: ImportError: gone",
                        f"only 2 engine modules found (expected at least {selftest.MIN_MODULES})"]


# --- the download tools ---

def test_the_built_in_yt_dlp_passes_the_check(tmp_path):
    support = tmp_path / "support"
    support.mkdir()
    assert selftest.check_download_tools(support, tmp_path) == []


def test_a_failing_check_is_reported(tmp_path):
    support = tmp_path / "support"
    support.mkdir()

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, '{"error": "ImportError: x"}\n', "ImportError: x")
    problems = selftest.check_download_tools(support, tmp_path, failing)
    assert problems == ["--check-tools failed (1): ImportError: x"]


# --- the conversion and the whole run ---

@pytest.mark.skipif(not PROGRAMS_HERE, reason=SKIP_WHY)
def test_a_tone_converts_to_aiff(tmp_path):
    assert selftest.check_conversion(tmp_path) == []


def test_arguments_are_refused(capsys):
    assert selftest.main(["--extra"]) == 2


@pytest.mark.skipif(not PROGRAMS_HERE, reason=SKIP_WHY)
def test_the_self_test_ignores_an_installed_update(tmp_path):
    support = tmp_path / "real support"
    install_update(support, "2099.1.1")  # a newer downloaded yt-dlp the self-test must not use
    before = sorted(str(p.relative_to(support)) for p in support.rglob("*"))
    env = {**os.environ, "DISCJOCKEY_SUPPORT": str(support)}
    r = subprocess.run([sys.executable, "-m", "discjockey.app_main", "--self-test"], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1] == "self-test passed"
    assert sorted(str(p.relative_to(support)) for p in support.rglob("*")) == before


# --- the failure path: a broken build must exit 1 and say why ---

def no_checks(monkeypatch, **replace):
    """Every check passes (returns []) except the ones in `replace`."""
    for name in ("check_modules", "check_imports", "check_programs", "check_conversion", "check_ui",
                 "check_download_tools", "check_licenses"):
        monkeypatch.setattr(selftest, name, replace.get(name, lambda *a, **k: []))


def test_a_failed_check_exits_one_and_names_it(monkeypatch, capsys):
    from types import SimpleNamespace
    from discjockey import tools
    monkeypatch.setattr(tools, "activate", lambda *a, **k: SimpleNamespace(bin_dir=None, override=None))
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", "unchanged")
    monkeypatch.setattr(selftest, "run_checks", lambda *a, **k: ["x is broken"])
    assert selftest.main([]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == ["FAIL x is broken", "self-test failed: 1 problem(s)"]


def test_the_self_test_uses_a_scratch_support_folder(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from discjockey import tools
    seen = {}

    def activate(*a, **k):
        seen["activate"] = k.get("support")
        return SimpleNamespace(bin_dir=None, override=None)

    def run_checks(work, support, bin_dir, frozen, run=None):
        seen["checks"] = support
        seen["env"] = os.environ.get("DISCJOCKEY_SUPPORT")
        return []
    monkeypatch.setattr(tools, "activate", activate)
    monkeypatch.setattr(selftest, "run_checks", run_checks)
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "users support"))
    assert selftest.main([]) == 0
    assert seen["activate"] == seen["checks"] and str(seen["checks"]) == seen["env"]
    assert "users support" not in seen["env"]


def test_the_frozen_app_needs_its_bundled_bin(monkeypatch, tmp_path):
    no_checks(monkeypatch)
    assert selftest.run_checks(tmp_path, tmp_path, None, frozen=True) == ["the app has no Contents/Resources/bin"]
    assert selftest.run_checks(tmp_path, tmp_path, None, frozen=False) == []


def test_the_frozen_app_checks_its_licences_folder(monkeypatch, tmp_path):
    from discjockey import tools
    seen = []
    no_checks(monkeypatch, check_licenses=lambda folder: seen.append(folder) or ["l"])
    monkeypatch.setattr(tools, "licenses_dir", lambda: tmp_path / "licenses")
    assert selftest.run_checks(tmp_path, tmp_path, tmp_path, frozen=True) == ["l"]
    assert seen == [tmp_path / "licenses"]
    assert selftest.run_checks(tmp_path, tmp_path, tmp_path, frozen=False) == []
    assert seen == [tmp_path / "licenses"]


def test_a_licences_folder_needs_its_index_and_every_file_it_names(tmp_path):
    folder = tmp_path / "licenses"
    assert selftest.check_licenses(folder) == [f"licences: {folder / 'INDEX.txt'} is missing"]
    folder.mkdir()
    (folder / "INDEX.txt").write_text("Discjockey bundles these components.\n\n")
    assert selftest.check_licenses(folder) == [f"licences: {folder / 'INDEX.txt'} lists nothing"]
    (folder / "INDEX.txt").write_text("Discjockey bundles these components.\n\nffmpeg 8: GPL -> ffmpeg.txt\n"
                                      "deno 2: MIT -> deno.txt\nmutagen 1.47: GPL-2.0\n")
    (folder / "ffmpeg.txt").write_text("notice")
    assert selftest.check_licenses(folder) == [f"licences: {folder / 'deno.txt'} is missing"]
    (folder / "deno.txt").write_text("MIT")
    assert selftest.check_licenses(folder) == []


def test_a_licences_folder_entry_needs_a_folder_with_texts(tmp_path):
    folder = tmp_path / "licenses"
    folder.mkdir()
    (folder / "INDEX.txt").write_text("Discjockey bundles these components.\n\nthe libraries -> libs/\n")
    assert selftest.check_licenses(folder) == [f"licences: {folder / 'libs/'} is missing"]
    (folder / "libs").mkdir()
    assert selftest.check_licenses(folder) == [f"licences: {folder / 'libs/'} has no texts"]  # there, but empty
    (folder / "libs" / "zlib.txt").write_text("Zlib")
    assert selftest.check_licenses(folder) == []


def test_run_checks_collects_every_problem(monkeypatch, tmp_path):
    no_checks(monkeypatch, check_modules=lambda *a, **k: ["m"], check_ui=lambda *a, **k: ["u"],
              check_download_tools=lambda *a, **k: ["d"])
    assert selftest.run_checks(tmp_path, tmp_path, tmp_path, frozen=False) == ["m", "u", "d"]


def check_answer(answer: str, returncode: int = 0):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, answer + "\n", "")
    return run


def test_the_update_check_must_find_the_built_in_version(tmp_path):
    import json
    from discjockey import tools
    support = tmp_path / "support"
    support.mkdir()
    builtin = tools.package_version(tools.builtin_package(support))
    right = json.dumps({"yt-dlp": builtin, "yt-dlp-ejs": "0.8.1"})
    assert selftest.check_download_tools(support, tmp_path, check_answer(right)) == []
    wrong = json.dumps({"yt-dlp": "1999.1.1", "yt-dlp-ejs": "0.8.1"})
    assert selftest.check_download_tools(support, tmp_path / "w", check_answer(wrong)) == [
        f"--check-tools found yt-dlp 1999.1.1, the built-in copy is {builtin}"]


def test_a_non_json_or_incomplete_check_answer_fails(tmp_path):
    support = tmp_path / "support"
    support.mkdir()
    for n, answer in enumerate(("not json", '{"yt-dlp": "1"}', "[]")):
        problems = selftest.check_download_tools(support, tmp_path / str(n), check_answer(answer))
        assert len(problems) == 1 and problems[0].startswith("--check-tools failed (0)")


def test_yt_dlp_must_be_the_built_in_copy(monkeypatch, tmp_path):
    import json
    from discjockey import tool_updates, tools
    support = tmp_path / "support"
    support.mkdir()
    builtin = tools.package_version(tools.builtin_package(support))
    right = check_answer(json.dumps({"yt-dlp": builtin, "yt-dlp-ejs": "0.8.1"}))
    for n, status in enumerate(({"version": builtin, "source": "updated"}, {"version": None, "source": "built_in"})):
        monkeypatch.setattr(tool_updates, "current_status", lambda s, status=status: {"yt-dlp": status})
        problems = selftest.check_download_tools(support, tmp_path / str(n), right)
        assert problems == [f"yt-dlp status: {status}"]


def test_a_good_answer_with_a_failing_exit_code_still_fails(tmp_path):
    import json
    from discjockey import tools
    support = tmp_path / "support"
    support.mkdir()
    builtin = tools.package_version(tools.builtin_package(support))
    answer = json.dumps({"yt-dlp": builtin, "yt-dlp-ejs": "0.8.1"})
    problems = selftest.check_download_tools(support, tmp_path, check_answer(answer, returncode=1))
    assert len(problems) == 1 and problems[0].startswith("--check-tools failed (1)")


# --- the import list ---

PYOBJC = {"objc", "AppKit", "Foundation", "WebKit", "Quartz", "Security", "UniformTypeIdentifiers", "CoreFoundation"}


def test_the_pyobjc_modules_checked_are_ones_the_app_imports():
    """PyInstaller bundles only what something imports. A framework pywebview merely depends on (Quartz) is left out of
    the frozen app, so demanding it made the build's self-test fail on a module nothing uses."""
    import importlib.util
    import re

    webview_dir = Path(importlib.util.find_spec("webview").submodule_search_locations[0])
    sources = (webview_dir / "platforms" / "cocoa.py").read_text()
    sources += "".join(p.read_text() for p in (REPO / "discjockey").rglob("*.py"))
    checked = PYOBJC.intersection(selftest.THIRD_PARTY)
    assert checked
    for name in checked:
        assert re.search(rf"^\s*(?:import|from) {name}\b", sources, re.M), f"nothing imports {name}"
