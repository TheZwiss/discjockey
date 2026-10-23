"""`python -m discjockey`: the programs and the download tools first (tools.activate), then the command line
(cli.py). `--check-tools <folder>` instead tests an update folder in this fresh process (spec public-release §6.4)."""
from __future__ import annotations

import sys

from . import tools


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [tools.CHECK_FLAG]:
        return tools.check_main(argv[1:])
    tools.activate()
    from . import cli  # imports yt_dlp (through run.py), so only after activate()
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
