import subprocess
import sys

import pytest

from discjockey.cli import parse_args


def test_parse_args_keeps_setup_and_update_and_needs_one():
    assert parse_args(["setup"]).command == "setup"
    assert parse_args(["update"]).command == "update"
    for argv in ([], ["--dry-run"], ["update", "--yes"]):  # the sync's flags went with the bare sync
        with pytest.raises(SystemExit):
            parse_args(argv)


def test_help_runs():
    r = subprocess.run([sys.executable, "-m", "discjockey", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "Discjockey" in r.stdout
