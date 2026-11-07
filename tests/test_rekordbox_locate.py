"""Finding rekordbox's library (discjockey/rekordbox/locate.py), whether rekordbox runs (process.py), and the two
conftest fixtures that keep every test away from the maintainer's rekordbox."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
from pathlib import Path

import pytest

from discjockey.rekordbox import process
from discjockey.rekordbox.locate import Place, app_version, locate

REAL_RUNNING = process.running  # taken at import, before conftest's stub replaces it for each test


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def options(home: Path, data) -> None:
    path = home / "Library/Application Support/Pioneer/rekordboxAgent/storage/options.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def install(apps: Path, folder: str, version) -> None:
    plist = apps / folder / "rekordbox.app/Contents/Info.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))


# --- the conftest fixtures ---

def test_every_test_sees_an_empty_rekordbox_folder_and_no_running_rekordbox(monkeypatch):
    folder = Path(os.environ["DISCJOCKEY_REKORDBOX"])
    assert folder.is_dir() and not any(folder.iterdir())
    assert locate() is None
    assert process.running() is False


def test_the_override_never_looks_at_home(monkeypatch, tmp_path):
    def no_home():
        raise AssertionError("locate read the home folder")
    monkeypatch.setattr(Path, "home", staticmethod(no_home))
    assert locate() is None
    touch(tmp_path / "rb/master.db")
    place = locate(env={"DISCJOCKEY_REKORDBOX": str(tmp_path / "rb")}, home=tmp_path / "no-such-home",
                   apps=tmp_path / "no-apps")
    assert place == Place(tmp_path / "rb/master.db", tmp_path / "rb/share", "override", None)


def test_an_override_with_only_rekordbox_5s_library_is_none(tmp_path):
    touch(tmp_path / "rb/datafile.edb")
    assert locate(env={"DISCJOCKEY_REKORDBOX": str(tmp_path / "rb")}) is None


# --- options.json, the default place, the version ---

def test_options_json_names_the_library_and_the_share_folder(tmp_path):
    db = touch(tmp_path / "elsewhere/master.db")
    options(tmp_path / "home", {"options": [["db-path", str(db)], ["analysis-data-root-path", str(tmp_path / "an")],
                                            ["settings-root-path", "/x"]]})
    install(tmp_path / "apps", "rekordbox 7", "7.2.3")
    place = locate(env={}, home=tmp_path / "home", apps=tmp_path / "apps")
    assert place == Place(db, tmp_path / "an", "options", "7.2.3")


def test_options_without_the_analysis_root_use_share_beside_the_library(tmp_path):
    db = touch(tmp_path / "elsewhere/master.db")
    options(tmp_path / "home", {"options": [["db-path", str(db)]]})
    place = locate(env={}, home=tmp_path / "home", apps=tmp_path / "apps")
    assert (place.share, place.source, place.app_version) == (tmp_path / "elsewhere/share", "options", None)


@pytest.mark.parametrize("data", [
    "not json",
    {"options": {"db-path": "x"}},                 # a mapping, not [name, value] pairs
    {"something": []},
    {"options": [["db-path", 7]]},
    {"options": [["db-path", "/no/such/master.db"]]},
    "edb",                                         # names rekordbox 5's library, not a master.db
])
def test_an_options_file_that_cant_be_used_falls_back_to_the_default_place(tmp_path, data):
    home = tmp_path / "home"
    if data == "edb":
        data = {"options": [["db-path", str(touch(tmp_path / "x/datafile.edb"))]]}
    options(home, data)
    db = touch(home / "Library/Pioneer/rekordbox/master.db")
    place = locate(env={}, home=home, apps=tmp_path / "apps")
    assert place == Place(db, db.parent / "share", "default", None)


def test_no_library_anywhere_is_none(tmp_path):
    touch(tmp_path / "home/Library/Pioneer/rekordbox/datafile.edb")  # rekordbox 5 only
    assert locate(env={}, home=tmp_path / "home", apps=tmp_path / "apps") is None


def test_the_newest_installed_version_wins_and_a_broken_plist_is_skipped(tmp_path):
    apps = tmp_path / "apps"
    install(apps, "rekordbox 6", "6.8.5")
    install(apps, "rekordbox 7", "7.10.0")
    install(apps, "rekordbox 7 old", "7.9.12")
    install(apps, "rekordbox 8 beta", 8)  # not a string
    broken = apps / "rekordbox 9/rekordbox.app/Contents/Info.plist"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a plist")
    assert app_version(apps) == "7.10.0"
    assert app_version(tmp_path / "none") is None


# --- process.running ---

def ps(monkeypatch, stdout="", returncode=0, error=None):
    def run(cmd, **kw):
        assert tuple(cmd) == ("/bin/ps", "-Axco", "comm=")
        if error:
            raise error
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")
    monkeypatch.setattr(process.subprocess, "run", run)


def test_rekordbox_runs_only_on_an_exact_process_name(monkeypatch):
    ps(monkeypatch, "launchd\nrekordboxAgent\nrekordbox helper\n")
    assert REAL_RUNNING() is False
    ps(monkeypatch, "launchd\n  rekordbox\nFinder\n")
    assert REAL_RUNNING() is True


@pytest.mark.parametrize("kw", [{"error": OSError("no ps")}, {"error": subprocess.TimeoutExpired("ps", 5)},
                                {"returncode": 1}])
def test_when_ps_cant_answer_rekordbox_counts_as_running(monkeypatch, kw):
    ps(monkeypatch, **kw)
    assert REAL_RUNNING() is True
