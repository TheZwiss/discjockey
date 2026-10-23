import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yt_dlp
import yt_dlp.version
import yt_dlp_ejs

from discjockey import REPO, tools
from tools_helpers import install_update, write_site, write_tools_folder


def frozen_app(tmp_path: Path, monkeypatch, with_bin: bool = True) -> Path:
    """Pretends this process is Discjockey.app/Contents/MacOS/Discjockey (PyInstaller sets sys.frozen)."""
    app = tmp_path / "Discjockey.app"
    exe = app / "Contents" / "MacOS" / "Discjockey"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    if with_bin:
        (app / "Contents" / "Resources" / "bin").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return app.resolve()


# --- versions ---

def test_versions_compare_as_numbers():
    assert tools.parse_version("2026.10.21") == (2026, 10, 21)
    assert tools.parse_version("2025.01.15") == tools.parse_version("2025.1.15")
    assert tools.parse_version("2026.10.21.1") > tools.parse_version("2026.10.21")
    for bad in (None, "", "2026.10.x", "v2026", "1..2", "²", " 2026.1.1"):
        assert tools.parse_version(bad) is None
    assert tools.newer("2026.10.28", "2026.10.21") and not tools.newer("2026.10.21", "2026.10.21")
    assert tools.newer("2026.10.21", None) and not tools.newer(None, "2026.10.21") and not tools.newer("x", None)
    assert tools.same_version("2025.01.15", "2025.1.15") and not tools.same_version(None, None)


def test_package_versions_are_read_without_importing(tmp_path):
    folder = write_tools_folder(tmp_path / "f", yt="2026.10.28", ejs="0.8.1")
    assert tools.package_version(folder / "yt_dlp") == "2026.10.28"
    assert tools.package_version(folder / "yt_dlp_ejs") == "0.8.1"
    assert tools.folder_version(folder) == "2026.10.28"
    assert tools.package_version(Path(yt_dlp.__file__).parent) == yt_dlp.version.__version__
    assert tools.package_version(Path(yt_dlp_ejs.__file__).parent) == yt_dlp_ejs.version
    shutil.rmtree(folder / "yt_dlp_ejs")
    assert tools.folder_version(folder) is None
    assert tools.package_version(tmp_path / "nothing" / "yt_dlp") is None


# --- the program's own folder and its bundled programs ---

def test_program_dir_is_the_checkout_or_the_app(tmp_path, monkeypatch):
    assert tools.program_dir() == REPO and tools.bundled_bin() is None
    app = frozen_app(tmp_path, monkeypatch)
    assert tools.program_dir() == app
    assert tools.bundled_bin() == app / "Contents" / "Resources" / "bin"


def test_an_app_without_a_bin_folder_has_no_bundled_programs(tmp_path, monkeypatch):
    frozen_app(tmp_path, monkeypatch, with_bin=False)
    assert tools.bundled_bin() is None


def test_activate_in_a_checkout_leaves_path_alone(tmp_path):
    env = {"PATH": "/opt/homebrew/bin:/usr/bin", "DISCJOCKEY_SUPPORT": str(tmp_path / "support")}
    a = tools.activate(env)
    assert env["PATH"] == "/opt/homebrew/bin:/usr/bin" and a.bin_dir is None
    assert a.override is None  # yt_dlp is imported in tests: never a second copy


def test_activate_in_the_app_puts_its_programs_first_once(tmp_path, monkeypatch):
    app = frozen_app(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bindir = str(app / "Contents" / "Resources" / "bin")
    env = {"PATH": f"/usr/bin:{bindir}:/bin", "DISCJOCKEY_SUPPORT": str(tmp_path / "support")}
    assert tools.activate(env).bin_dir == Path(bindir)
    tools.activate(env)
    assert env["PATH"] == f"{bindir}:/usr/bin:/bin"
    assert sys.dont_write_bytecode is True
    empty = {"DISCJOCKEY_SUPPORT": str(tmp_path / "support")}
    tools.activate(empty)
    assert empty["PATH"] == bindir


# --- the update folder on sys.path ---

@pytest.fixture
def layout(tmp_path):
    """A built-in yt-dlp 2026.10.21 in site/, an empty support folder."""
    return write_site(tmp_path / "site", yt="2026.10.21"), tmp_path / "Application Support" / "Discjockey"


def test_a_newer_update_comes_first(layout):
    site, support = layout
    folder = install_update(support, "2026.10.28")
    path = [str(site)]
    assert tools.insert_override(support, path, {}) == folder
    assert path == [str(folder), str(site)]
    assert tools.insert_override(support, path, {}) == folder and path.count(str(folder)) == 1
    assert tools.builtin_package(support, path) == (site / "yt_dlp").resolve()


@pytest.mark.parametrize("version", ["2026.10.21", "2026.10.14", "2026.1.2"])
def test_the_built_in_copy_wins_unless_the_update_is_newer(layout, version):
    site, support = layout
    install_update(support, version)
    path = [str(site)]
    assert tools.insert_override(support, path, {}) is None and path == [str(site)]


def test_no_update_or_a_broken_one_uses_the_built_in_copy(layout):
    site, support = layout
    assert tools.insert_override(support, [str(site)], {}) is None  # no tools folder at all
    folder = install_update(support, "2026.10.28")
    shutil.rmtree(folder / "yt_dlp_ejs")  # half there
    assert tools.current_folder(support) is None
    assert tools.insert_override(support, [str(site)], {}) is None
    shutil.rmtree(folder)  # current points at nothing
    assert tools.current_folder(support) is None
    assert tools.insert_override(support, [str(site)], {}) is None


def test_current_must_stay_inside_the_tools_folder(layout, tmp_path):
    site, support = layout
    outside = write_tools_folder(tmp_path / "elsewhere", yt="2026.10.28")
    tools.tools_root(support).mkdir(parents=True)
    (tools.tools_root(support) / tools.CURRENT).symlink_to(outside)
    assert tools.current_folder(support) is None


def test_never_once_yt_dlp_is_imported(layout):
    site, support = layout
    install_update(support, "2026.10.28")
    path = [str(site)]
    assert tools.insert_override(support, path, {"yt_dlp": object()}) is None and path == [str(site)]


def test_an_unknown_built_in_version_lets_a_valid_update_in(tmp_path):
    support = tmp_path / "support"
    folder = install_update(support, "2026.10.28")
    assert tools.insert_override(support, [str(tmp_path / "empty")], {}) == folder


def test_activating_an_update_folder_marks_it_in_use(layout, monkeypatch):
    site, support = layout
    folder = install_update(support, "2026.10.28")
    held = []
    monkeypatch.setattr(tools, "_held", held)
    assert tools.insert_override(support, [str(site)], {}) == folder
    try:
        assert len(held) == 1 and tools.remove_unless_in_use(folder) is False
    finally:
        for fd in held:
            os.close(fd)


def test_running_package_is_the_imported_one():
    assert tools.running_package() == Path(yt_dlp.__file__).resolve().parent


# --- the check in a process of its own ---

def run_check(folder: Path) -> subprocess.CompletedProcess:
    cmd, cwd = tools.check_command(folder)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def last_json(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_check_command_in_a_checkout_and_in_the_app(tmp_path, monkeypatch):
    assert tools.check_command(tmp_path) == ([sys.executable, "-m", "discjockey", "--check-tools", str(tmp_path)],
                                             REPO)
    frozen_app(tmp_path, monkeypatch)
    assert tools.check_command(tmp_path) == ([sys.executable, "--check-tools", str(tmp_path)], None)


def test_the_check_passes_a_good_folder(tmp_path):
    folder = write_tools_folder(tmp_path / "Application Support" / "tools" / ".partial-2026.10.28",
                                yt="2026.10.28", ejs="0.8.1")
    r = run_check(folder)
    assert r.returncode == 0, r.stderr
    assert last_json(r) == {"yt-dlp": "2026.10.28", "yt-dlp-ejs": "0.8.1"}


def test_the_check_passes_the_real_yt_dlp(tmp_path):
    folder = tmp_path / "real"
    for module in (yt_dlp, yt_dlp_ejs):
        src = Path(module.__file__).parent
        shutil.copytree(src, folder / src.name, ignore=shutil.ignore_patterns("__pycache__"))
    r = run_check(folder)
    assert r.returncode == 0, r.stderr
    assert last_json(r) == {"yt-dlp": yt_dlp.version.__version__, "yt-dlp-ejs": yt_dlp_ejs.version}


@pytest.mark.parametrize("damage", ["import_error", "no_ejs", "no_solver", "no_extractors"])
def test_the_check_fails_a_bad_folder(tmp_path, damage):
    folder = write_tools_folder(tmp_path / "bad", yt="2026.10.28")
    if damage == "import_error":
        (folder / "yt_dlp" / "__init__.py").write_text("import a_module_that_is_not_there\n")
    elif damage == "no_ejs":  # the child would import the installed yt_dlp_ejs instead: refused
        shutil.rmtree(folder / "yt_dlp_ejs")
    elif damage == "no_solver":
        (folder / "yt_dlp_ejs" / "yt" / "solver" / "core.min.js").unlink()
    else:
        (folder / "yt_dlp" / "extractor" / "__init__.py").write_text("def gen_extractor_classes():\n    return []\n")
    r = run_check(folder)
    assert r.returncode == 1 and r.stderr.strip()


def test_the_check_needs_exactly_one_folder():
    assert tools.check_main([]) == 2 and tools.check_main(["a", "b"]) == 2


# --- the entry: activate first, the command line after ---

def test_python_m_discjockey_activates_before_the_command_line(monkeypatch):
    import discjockey.__main__ as entry
    from discjockey import cli
    order = []
    monkeypatch.setattr(tools, "activate", lambda *a, **k: order.append("activate"))
    monkeypatch.setattr(cli, "main", lambda argv: order.append(("cli", argv)) or 0)
    assert entry.main(["--dry-run"]) == 0
    assert order == ["activate", ("cli", ["--dry-run"])]


def test_check_tools_runs_without_activating(monkeypatch, tmp_path):
    import discjockey.__main__ as entry
    monkeypatch.setattr(tools, "activate", lambda *a, **k: pytest.fail("must not activate"))
    monkeypatch.setattr(tools, "check_main", lambda args: 7 if args == [str(tmp_path)] else 0)
    assert entry.main(["--check-tools", str(tmp_path)]) == 7


# --- fix round 1 ---

def test_the_check_fails_a_candidate_that_exits_by_itself(tmp_path):
    folder = write_tools_folder(tmp_path / "exits", yt="2026.10.28")
    (folder / "yt_dlp" / "__init__.py").write_text("import sys\nsys.exit(0)\n")
    r = run_check(folder)
    assert r.returncode == 1 and "SystemExit" in r.stderr
    assert "error" in last_json(r) and "yt-dlp" not in last_json(r)


def test_check_main_reports_system_exit_as_a_failure(tmp_path, monkeypatch, capsys):
    def boom(folder):
        raise SystemExit(0)
    monkeypatch.setattr(tools, "_check", boom)
    assert tools.check_main([str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert "SystemExit" in out.err and "error" in json.loads(out.out.strip().splitlines()[-1])


def test_activate_inserts_the_update_into_sys_path_and_stays_the_same_when_called_again(tmp_path, monkeypatch):
    site = write_site(tmp_path / "site", yt="2026.10.21")
    support = tmp_path / "support"
    folder = install_update(support, "2026.10.28")
    monkeypatch.setattr(sys, "path", [str(site)])
    for name in (tools.YT_DLP, tools.EJS):  # as at the start of a fresh process
        monkeypatch.delitem(sys.modules, name, raising=False)
    env = {"DISCJOCKEY_SUPPORT": str(support)}
    first = tools.activate(env)
    assert first.override == folder and sys.path == [str(folder), str(site)]
    assert tools.activate(env) == first and sys.path.count(str(folder)) == 1
    # later the update's yt_dlp is imported: the answer stays the same
    module = type(sys)("yt_dlp")
    module.__file__ = str(folder / "yt_dlp" / "__init__.py")
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    assert tools.activate(env) == first


def test_licenses_dir_in_a_checkout_and_in_the_app(tmp_path, monkeypatch):
    assert tools.licenses_dir() == REPO / "packaging" / "licenses"
    app = frozen_app(tmp_path, monkeypatch)
    assert tools.licenses_dir() == app / "Contents" / "Resources" / "licenses"
