"""Discjockey.app's program (spec public-release §5): this process is the app, so the Dock shows Discjockey with its
icon. The order matters (phase 3 final review):
1. `--check-tools <folder>`: the update check's child process (tools.check_main), before anything imports yt-dlp,
   webview or AppKit. A webview import here would start a Cocoa app for every update test.
2. `--self-test`: the build's own test (selftest.py). It activates against a scratch support folder of its own.
3. Started by LaunchServices (the Finder, the Dock, `open`): no argument and the parent is launchd (pid 1), or the single
   argument `-psn_…` macOS passes: tools.activate() (bundled programs first on PATH, a newer yt-dlp first on sys.path),
   then the window.
4. Anything else goes to the command line (issue 39, design §2.1): tools.activate(), then cli.main. That includes
   `app open`, which opens the window from anywhere, and no argument from a shell, which prints the short help and
   exits 0 (a window that opens on the user's screen would block an agent's first probe). The parser (cli/parser.py)
   is the one list of commands: `/Applications/Discjockey.app/Contents/MacOS/Discjockey <command> …` runs any of them.
PyInstaller runs packaging/launch.py, which only calls main(): an entry script can't use relative imports."""
from __future__ import annotations

import os
import sys

from . import tools

SELF_TEST_FLAG = "--self-test"
LAUNCHD_PID = 1
FINDER_ARGUMENT = "-psn_"  # what macOS passes to an app opened from the Finder: `-psn_0_12345`


def started_by_launchd(argv: list[str]) -> bool:
    """Whether LaunchServices started this process: no argument and a launchd parent, or the one `-psn_…` argument."""
    if not argv:
        return os.getppid() == LAUNCHD_PID
    return len(argv) == 1 and argv[0].startswith(FINDER_ARGUMENT)


def main(argv: list[str] | None = None) -> int:
    if tools.is_frozen():
        sys.dont_write_bytecode = True  # nothing may be written into the signed bundle
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [tools.CHECK_FLAG]:
        return tools.check_main(argv[1:])
    if argv[:1] == [SELF_TEST_FLAG]:
        from . import selftest
        return selftest.main(argv[1:])
    tools.activate()
    if started_by_launchd(argv):
        from . import library
        from .hub import app  # imports yt_dlp through the engine, so only after activate()
        return app.main(library.resolve_paths())
    from . import cli
    return cli.main(argv or ["help"])  # no argument from a shell: the short help, never a window


if __name__ == "__main__":
    sys.exit(main())
