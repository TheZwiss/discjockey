"""Discjockey.app's program (spec public-release §5): this process is the app, so the Dock shows Discjockey with its
icon. The order matters (phase 3 final review):
1. `--check-tools <folder>`: the update check's child process (tools.check_main), before anything imports yt-dlp,
   webview or AppKit. A webview import here would start a Cocoa app for every update test.
2. `--self-test`: the build's own test (selftest.py). It activates against a scratch support folder of its own.
3. A known console command (`CLI_COMMANDS`, e.g. `rekordbox restore <name> --yes`, `batch undo 3`): tools.activate(),
   then cli.main. The app has no `discjockey` command of its own, so this is how a user of the app reaches them from
   the Terminal: `/Applications/Discjockey.app/Contents/MacOS/Discjockey <command> …`.
4. Otherwise tools.activate() (bundled programs first on PATH, a newer yt-dlp first on sys.path), then the hub.
PyInstaller runs packaging/launch.py, which only calls main(): an entry script can't use relative imports. Unknown
arguments (Finder may pass one) are ignored."""
from __future__ import annotations

import sys

from . import tools

SELF_TEST_FLAG = "--self-test"
# cli.py's sub-commands. Kept here because cli.py imports yt-dlp and may only be imported after tools.activate();
# a test pins this list against cli.parse_args.
CLI_COMMANDS = ("setup", "update", "upgrades", "upgrade", "batch", "hub", "rekordbox", "settings")


def main(argv: list[str] | None = None) -> int:
    if tools.is_frozen():
        sys.dont_write_bytecode = True  # nothing may be written into the signed bundle
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [tools.CHECK_FLAG]:
        return tools.check_main(argv[1:])
    if argv[:1] == [SELF_TEST_FLAG]:
        from . import selftest
        return selftest.main(argv[1:])
    if argv[:1] and argv[0] in CLI_COMMANDS:
        tools.activate()
        from . import cli
        return cli.main(argv)
    tools.activate()
    from . import library
    from .hub import app  # imports yt_dlp through the engine, so only after activate()
    return app.main(library.resolve_paths())


if __name__ == "__main__":
    sys.exit(main())
