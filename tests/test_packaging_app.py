import subprocess
import tomllib

import pytest

import discjockey
from discjockey import REPO
from packaging_helpers import PACKAGING, load

app_info = load("app_info")
machos = load("machos")


def test_info_plist():
    info = app_info.info_plist("1.2.3")
    assert info["CFBundleIdentifier"] == "io.github.thezwiss.discjockey" and info["CFBundleName"] == "Discjockey"
    assert info["CFBundleShortVersionString"] == info["CFBundleVersion"] == "1.2.3"
    assert info["LSMinimumSystemVersion"] == "12.0" == machos.MAX_MINOS
    assert info["NSHighResolutionCapable"] is True
    for key in ("NSDownloadsFolderUsageDescription", "NSDesktopFolderUsageDescription",
                "NSDocumentsFolderUsageDescription", "NSRemovableVolumesUsageDescription",
                "NSNetworkVolumesUsageDescription"):
        assert info[key].startswith("Discjockey ")


def test_the_spec_keeps_what_the_app_relies_on():
    spec = (PACKAGING / "discjockey.spec").read_text()
    assert 'module_collection_mode={"yt_dlp": "py", "yt_dlp_ejs": "py"}' in spec
    assert 'target_arch="arm64"' in spec and '"launch.py"' in spec and "app_info.info_plist(VERSION)" in spec


def test_the_licences_come_from_what_pyinstaller_collected():
    spec = (PACKAGING / "discjockey.spec").read_text()
    assert "collect_licenses.toc_sources(a.pure, a.binaries, a.datas)" in spec
    assert '"--bundled", str(BUNDLED)' in spec and "a.datas + licenses" in spec
    assert '"licenses")]' not in spec  # not as an Analysis input: it doesn't exist before Analysis


def test_the_launcher_only_calls_app_main():
    assert "from discjockey.app_main import main" in (PACKAGING / "launch.py").read_text()


def test_the_dmg_has_the_app_an_arrow_and_applications():
    settings = {"defines": {"app": "/x/dist/app/Discjockey.app"}}
    exec((PACKAGING / "dmg_settings.py").read_text(), settings)
    assert settings["files"] == ["/x/dist/app/Discjockey.app"]
    assert settings["symlinks"] == {"Applications": "/Applications"}
    assert settings["background"] == "builtin-arrow"
    assert set(settings["icon_locations"]) == {"Discjockey.app", "Applications"}


def test_the_build_tools_are_pinned():
    groups = tomllib.loads((REPO / "pyproject.toml").read_text())["dependency-groups"]
    assert "pyinstaller==6.22.3" in groups["build"]


def test_build_app_sh_parses():
    subprocess.run(["bash", "-n", str(REPO / "scripts" / "build_app.sh")], check=True)


def run_build_copy(tmp_path, stubs=None, prepare=None, **env):
    """Runs a copy of the script in a scratch tree, never the checkout's dist/, with an earlier .dmg in its dist/.
    No npm or uv on PATH and UV=false: if a check under test ever broke, the build would fail at once. `stubs`
    ({name: shell script}) are programs put first on PATH; `prepare(tmp_path)` runs once the tree is written."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "discjockey").mkdir()
    (tmp_path / "dist").mkdir()
    script = tmp_path / "scripts" / "build_app.sh"
    script.write_text((REPO / "scripts" / "build_app.sh").read_text())
    (tmp_path / "discjockey" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    earlier = tmp_path / "dist" / "Discjockey-9.9.9.dmg"
    earlier.write_text("an earlier build")
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    for name, body in (stubs or {}).items():
        (bin_dir / name).write_text("#!/bin/bash\n" + body)
        (bin_dir / name).chmod(0o755)
    if prepare:
        prepare(tmp_path)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "UV": "/usr/bin/false", **env}
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30), earlier


@pytest.mark.parametrize("name", ["REQUIRE_IDENTITY", "SKIP_UI_BUILD"])
def test_a_flag_value_the_build_does_not_understand_is_refused_before_anything_runs(name, tmp_path):
    r, earlier = run_build_copy(tmp_path, **{name: "on"})
    assert r.returncode == 2
    assert f"{name}=on is not understood" in r.stderr and "==>" not in r.stdout
    assert earlier.read_text() == "an earlier build"


def test_a_failed_step_is_named_and_an_earlier_dmg_stays(tmp_path):
    r, earlier = run_build_copy(tmp_path, SKIP_UI_BUILD="yes")
    assert r.returncode != 0 and "==> [2/8] build venv" in r.stdout
    assert r.stderr.strip().endswith(
        "Build failed in step 2/8 (build venv (macOS 12 wheels for arm64)): see the lines above.")
    assert earlier.read_text() == "an earlier build"


NPM = """[ "$1" = ci ] && exit 0
while [ $# -gt 0 ]; do
  if [ "$1" = --outDir ]; then mkdir -p "$2"; echo new > "$2/index.html"; fi
  shift
done
"""

# the programs the stub uv puts into the venv it "makes"
FAKE_PYINSTALLER = """while [ $# -gt 0 ]; do if [ "$1" = --distpath ]; then d="$2"; fi; shift; done
mkdir -p "$d/Discjockey.app/Contents/MacOS"
printf '#!/bin/bash\\nexit 0\\n' > "$d/Discjockey.app/Contents/MacOS/Discjockey"
chmod +x "$d/Discjockey.app/Contents/MacOS/Discjockey"
"""
FAKE_DMGBUILD = """for last; do :; done
echo dmg > "$last"
"""
UV = """here="$(dirname "$0")"
case "$1" in
  export) while [ $# -gt 0 ]; do if [ "$1" = -o ]; then echo > "$2"; fi; shift; done ;;
  venv)
    mkdir -p "${@: -1}/bin"
    printf '#!/bin/bash\\nexit 0\\n' > "${@: -1}/bin/python"
    cp "$here/fake_pyinstaller" "${@: -1}/bin/pyinstaller"
    cp "$here/fake_dmgbuild" "${@: -1}/bin/dmgbuild"
    chmod +x "${@: -1}"/bin/* ;;
  *) exit 0 ;;
esac
"""


def test_a_ui_that_differs_from_the_committed_one_stops_the_build_and_changes_nothing(tmp_path):
    def prepare(root):
        (root / "hub-ui").mkdir()
        (root / "discjockey" / "hub" / "static").mkdir(parents=True)
        (root / "discjockey" / "hub" / "static" / "index.html").write_text("old")
    r, earlier = run_build_copy(tmp_path, stubs={"npm": NPM}, prepare=prepare)
    assert r.returncode == 1
    assert "is not what hub-ui builds now" in r.stderr and "Build failed in step 1/8" in r.stderr
    assert (tmp_path / "discjockey" / "hub" / "static" / "index.html").read_text() == "old"
    assert earlier.read_text() == "an earlier build"


def test_a_dmg_that_cannot_be_checked_is_removed(tmp_path):
    stubs = {"uv": UV, "fake_pyinstaller": FAKE_PYINSTALLER, "fake_dmgbuild": FAKE_DMGBUILD, "hdiutil": 'case "$1" in attach) exit 1 ;; *) exit 0 ;; esac\n'}
    r, earlier = run_build_copy(tmp_path, stubs=stubs, SKIP_UI_BUILD="yes", UV=str(tmp_path / "stubs" / "uv"))
    assert r.returncode != 0 and "Build failed in step 8/8" in r.stderr, r.stderr
    assert not earlier.exists()  # this run replaced the earlier .dmg, then removed its own half-checked one


@pytest.mark.parametrize("flag, refused", [("REQUIRE_IDENTITY", True), (None, False)])
def test_a_release_build_needs_a_clean_checkout(tmp_path, flag, refused):
    def prepare(root):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
        subprocess.run([*git[:5], "init", "-q", str(root)], check=True)
        subprocess.run([*git, "add", "scripts", "discjockey"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        with (root / "discjockey" / "__init__.py").open("a") as f:
            f.write("# edited after the commit\n")
    r, earlier = run_build_copy(tmp_path, prepare=prepare, SKIP_UI_BUILD="yes", **({flag: "1"} if flag else {}))
    assert r.returncode != 0
    if refused:
        assert "a release build needs a clean checkout" in r.stderr and "==>" not in r.stdout
    else:
        assert "a release build needs a clean checkout" not in r.stderr and "==> [1/8]" in r.stdout


def test_the_dmg_is_named_after_the_version():
    assert 'Discjockey-$VERSION.dmg' in (REPO / "scripts" / "build_app.sh").read_text()
    assert discjockey.__version__
