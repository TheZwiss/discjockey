import os
import subprocess
import sys

import pytest

from discjockey import REPO, app_main, tools


def test_check_tools_comes_first(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "activate", lambda *a, **k: pytest.fail("must not activate"))
    monkeypatch.setattr(tools, "check_main", lambda args: 7 if args == [str(tmp_path)] else 0)
    assert app_main.main([tools.CHECK_FLAG, str(tmp_path)]) == 7


def test_the_self_test_starts_no_hub(monkeypatch):
    import discjockey.selftest as selftest
    monkeypatch.setattr(tools, "activate", lambda *a, **k: pytest.fail("the self-test activates on its own"))
    monkeypatch.setattr(selftest, "main", lambda args: 3 if args == [] else 0)
    assert app_main.main([app_main.SELF_TEST_FLAG]) == 3


def stub_window(monkeypatch):
    """Records the order of activate, resolve and the hub's start; a window never opens."""
    from discjockey import library
    from discjockey.hub import app
    order = []
    monkeypatch.setattr(tools, "activate", lambda *a, **k: order.append("activate"))
    monkeypatch.setattr(library, "resolve_paths", lambda *a, **k: order.append("resolve") or "resolved")
    monkeypatch.setattr(app, "main", lambda resolved: order.append(("hub", resolved)) or 0)
    return order


@pytest.mark.parametrize("argv,parent", [([], 1), (["-psn_0_12345"], 4242), (["-psn_0_12345"], 1)])
def test_t12_a_finder_start_opens_the_window(monkeypatch, argv, parent):
    """LaunchServices: no argument with launchd as the parent, or the single `-psn_…` macOS passes."""
    order = stub_window(monkeypatch)
    monkeypatch.setattr(os, "getppid", lambda: parent)
    assert app_main.main(argv) == 0
    assert order == ["activate", "resolve", ("hub", "resolved")]


def test_t12_no_argument_from_a_shell_prints_the_short_help_and_opens_nothing(tmp_path):
    """The parent here is pytest, not launchd: the first line names the program's `help --json`; no webview import."""
    code = ("import sys, discjockey.app_main as m; code = m.main([]); "
            "print('webview' in sys.modules, code, file=sys.stderr); sys.exit(code)")
    env = {**os.environ, "DISCJOCKEY_SUPPORT": str(tmp_path / "support"), "DISCJOCKEY_REKORDBOX": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    first = r.stdout.splitlines()[0]
    assert first.startswith("AI agents: run `") and first.endswith(" help --json` first.")
    assert "False 0" in r.stderr.splitlines()[-1]


def test_t12_app_open_opens_the_window_from_a_shell(monkeypatch):
    order = stub_window(monkeypatch)
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    assert app_main.main(["app", "open"]) == 0
    assert order == ["activate", "resolve", ("hub", "resolved")]


@pytest.mark.parametrize("argv", [["rekordbox", "restore", "x", "--yes"], ["--yes", "--json"], ["where"],
                                  ["-psn_0_1", "--json"], ["--help"], ["hub"], ["help", "--json"]])
def test_t12_any_other_argument_reaches_the_command_line_even_from_launchd(monkeypatch, argv):
    from discjockey import cli
    from discjockey.hub import app
    order = []
    monkeypatch.setattr(os, "getppid", lambda: 1)
    monkeypatch.setattr(tools, "activate", lambda *a, **k: order.append("activate"))
    monkeypatch.setattr(cli, "main", lambda args: order.append(("cli", args)) or 4)
    monkeypatch.setattr(app, "main", lambda resolved: pytest.fail("a command must not open the window"))
    assert app_main.main(argv) == 4
    assert order == ["activate", ("cli", argv)]


def test_importing_the_entry_starts_nothing():
    code = ("import sys, discjockey.app_main; "
            "print(sorted(m for m in ('webview', 'AppKit', 'yt_dlp') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "[]"


def test_the_frozen_app_writes_no_bytecode(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(tools, "check_main", lambda args: 0)
    app_main.main([tools.CHECK_FLAG, str(tmp_path)])
    assert sys.dont_write_bytecode is True


def test_yt_dlp_is_imported_only_after_activate():
    """The update only applies if nothing imported yt_dlp (the hub does, through the engine) before activate()."""
    code = """
import json, os, sys
from discjockey import app_main, library, tools
seen = {}
real = tools.activate
def activate(*a, **k):
    seen["yt_dlp"] = "yt_dlp" in sys.modules
    seen["hub"] = "discjockey.hub.app" in sys.modules
    return real(*a, **k)
def resolve():
    seen["hub_by_resolve"] = "discjockey.hub.app" in sys.modules
    print(json.dumps(seen), flush=True)
    os._exit(0)
tools.activate = activate
library.resolve_paths = resolve
app_main.main(["-psn_0_1"])
"""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as support:
        env = {**os.environ, "DISCJOCKEY_SUPPORT": support}
        r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True,
                           check=True)
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"yt_dlp": False, "hub": False, "hub_by_resolve": True}
