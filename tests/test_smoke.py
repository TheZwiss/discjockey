import subprocess
import sys

from discjockey.cli import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.command is None
    assert (args.yes, args.dry_run, args.limit, args.verbose) == (False, False, None, False)


def test_parse_args_flags():
    args = parse_args(["--dry-run", "--limit", "3", "--yes", "--verbose"])
    assert (args.yes, args.dry_run, args.limit, args.verbose) == (True, True, 3, True)
    assert parse_args(["setup"]).command == "setup"
    assert parse_args(["update"]).command == "update"


def test_help_runs():
    r = subprocess.run([sys.executable, "-m", "discjockey", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "Discjockey" in r.stdout
