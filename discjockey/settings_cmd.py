"""`discjockey settings …`: the window's Settings from the Terminal, one setting per sub-command (issue 33 stage C; plan
stage C §2). Today only `auto-upgrade [on|off]`: without a value it prints the current one (a read: no lock), with one
it takes the library lock as every settings write does, saves and prints the new value.

Exit codes: 0 done (or read), 1 the settings file can't be read (the message names the problem), 2 no music folder
chosen yet or its drive isn't there, 3 busy (another run holds the library lock; nothing was changed). `--json` prints
one object: `{"ok": true, "auto_upgrade": bool}`, or `{"ok": false, "kind", "message"}` for a problem. The settings are
the same file the window writes (`settings.json` in the support folder), so the window shows the value at once.
"""
from __future__ import annotations

import argparse
from dataclasses import replace

from . import library
from .library import LockHeld, NoLibrary
from .rekordbox_cmd import failed, no_library, say
from .settings import SettingsError, load_settings, save_settings

OK, FAILED, NO_LIBRARY, BUSY = 0, 1, 2, 3
LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."


def add_commands(commands) -> None:
    """Adds `settings` (with `auto-upgrade`) to the top-level sub-commands."""
    settings = commands.add_parser("settings", description="Change a setting without the window.")
    steps = settings.add_subparsers(dest="settings_command", metavar="setting", required=True)
    auto = steps.add_parser(
        "auto-upgrade", help="upgrade automatically at the end of a sync (Settings › Upgrades)",
        description="Whether a sync ends with the upgrades that need no decision (the same recording as your file, "
                    "measured to the sample), while rekordbox is closed. On by default. Without on or off it "
                    "prints the current value.")
    auto.add_argument("value", nargs="?", choices=("on", "off"), help="on or off; leave out to read it")
    auto.add_argument("--json", action="store_true", help="print one JSON object")


def line(on: bool) -> str:
    return f"Upgrade automatically when I sync: {'on' if on else 'off'}"


def run_auto_upgrade(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    paths = resolved.paths
    try:
        settings = load_settings(paths.settings_file)
        if args.value is None:  # a read: no lock, nothing written
            say(args, {"ok": True, "auto_upgrade": settings.auto_upgrade}, [line(settings.auto_upgrade)])
            return OK
        with library.run_lock(paths.lock):
            settings = load_settings(paths.settings_file)  # as the lock holder sees it
            on = args.value == "on"
            save_settings(paths.settings_file, replace(settings, auto_upgrade=on))
        say(args, {"ok": True, "auto_upgrade": on}, [line(on)])
        return OK
    except SettingsError as e:
        return failed(args, str(e), "refused", "settings_invalid", code=FAILED)
    except NoLibrary as e:
        return failed(args, str(e), "refused", "no_library", code=NO_LIBRARY)
    except LockHeld:
        return failed(args, LOCK_HELD, "busy", code=BUSY)


def run(args: argparse.Namespace) -> int:
    """Dispatches the sub-commands of this module; `cli.main` calls it for `settings`."""
    return {"auto-upgrade": run_auto_upgrade}[args.settings_command](args)
