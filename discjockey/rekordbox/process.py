"""Whether rekordbox is running (design rekordbox-repoint §5.3 guard 3).

`running()` lists the process names with `/bin/ps -Axco comm=` and looks for a line that is exactly `rekordbox`:
`rekordboxAgent` (the cloud helper that keeps running after rekordbox quits) doesn't count. When `ps` can't answer,
rekordbox counts as running, the safe side for every write guard; the read side then still opens without leaving a
file (`master.open_read`).
"""
from __future__ import annotations

import subprocess

PS = ("/bin/ps", "-Axco", "comm=")
NAME = "rekordbox"
TIMEOUT = 5  # seconds


def running() -> bool:
    try:
        r = subprocess.run(PS, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return True
    if r.returncode != 0:
        return True
    return any(line.strip() == NAME for line in r.stdout.splitlines())
