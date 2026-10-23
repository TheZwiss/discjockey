"""The port of the window's page server (issue 17). pywebview serves the page from http://127.0.0.1:<port>/ and the
window's saved settings (localStorage) belong to that address, so the port has to stay the same from one start to the
next, and it has to be ours: when another program already listens there, pywebview's server fails without a word
(its bind runs in a thread of its own) and the window shows whatever answers. pywebview's own fixed port (42001 with
private_mode=False) is shared by every pywebview app.

So: a port picked at random once (20000-32767, below macOS's range for outgoing connections) and kept in
<support>/window.json. At every start it is used while it is free; when another program holds it, a new one is picked
and kept (the saved settings start over once). A second Discjockey window on the same support folder (the lock
<support>/.window.lock is held while a window is open) takes a free port for its session only and leaves the saved
one to the first. "Free" is checked by binding as the page server will (127.0.0.1, SO_REUSEADDR like http.server):
a port the last session left in TIME_WAIT is free, one another program listens on 127.0.0.1 is not. (A program
listening on all addresses, 0.0.0.0, does not block it: our more specific socket still gets the connections.) Windows
that start together without the lock choose their session ports independently; a clash is as unlikely as the
check-then-bind gap and is accepted."""
from __future__ import annotations

import fcntl
import json
import logging
import random
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable

from ..library import SupportPaths, write_json_atomic

LOW, HIGH = 20000, 32768  # random.randrange(LOW, HIGH): 20000-32767
TRIES = 50
log = logging.getLogger(__name__)


def port_free(port: int) -> bool:
    """True when the page server can listen on 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _system_port() -> int:
    """A port the system picks (always free; outside our range, so it isn't kept past the next start)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick(free: Callable[[int], bool], rand: Callable[[], int], avoid: int | None) -> int:
    for _ in range(TRIES):
        port = rand()
        if port != avoid and free(port):
            return port
    return _system_port()


def _read_port(path: Path) -> int | None:
    try:
        port = json.loads(path.read_text(encoding="utf-8"))["port"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not LOW <= port < HIGH:
        return None
    return port


def _take_lock(path: Path) -> tuple[bool, IO | None]:
    """(True, the open lock file) when no other Discjockey window uses this support folder; (False, None) when one
    does. A lock that can't be made at all (the support folder can't be written) counts as ours: nothing is shared."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a")
    except OSError:
        return True, None
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return False, None
    except OSError:
        f.close()
        return True, None
    return True, f


@dataclass
class WindowPort:
    port: int
    kept: bool  # saved in window.json for the next start; False: for this session only
    lock: IO | None = None  # held while the window is open

    def release(self) -> None:
        if self.lock is not None:
            self.lock.close()  # closing the file lets go of the flock
            self.lock = None


def window_port(support: Path, *, free: Callable[[int], bool] = port_free,
                rand: Callable[[], int] | None = None) -> WindowPort:
    """The port for this window (see the module docstring). Never fails."""
    paths = SupportPaths(support=support)
    rand = rand or (lambda: random.SystemRandom().randrange(LOW, HIGH))
    first, lock = _take_lock(paths.window_lock)
    saved = _read_port(paths.window_file)
    if not first:
        return WindowPort(_pick(free, rand, avoid=saved), kept=False)
    if saved is not None and free(saved):
        return WindowPort(saved, kept=True, lock=lock)
    port = _pick(free, rand, avoid=saved)
    if not LOW <= port < HIGH:  # the system's pick when no random one was free: not kept, the next start picks again
        return WindowPort(port, kept=False, lock=lock)
    try:
        write_json_atomic(paths.window_file, {"port": port}, parents=True, indent=2)
    except OSError as e:
        log.warning("window port: couldn't keep %s: %s", port, e)
        return WindowPort(port, kept=False, lock=lock)
    return WindowPort(port, kept=True, lock=lock)
