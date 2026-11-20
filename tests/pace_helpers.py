"""Seams for the shared pacer: a clock whose sleep moves it, a rng with the shortest draws, and a pacer that never
really waits."""
import random
import time
from pathlib import Path

from discjockey.events import no_emit
from discjockey.pacing import SharedPacer


class FakeClock:
    """`time` and `sleep` for `SharedPacer(clock=..., sleep=...)`: a sleep moves the clock instead of waiting."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class ScaledRng(random.Random):
    """Every `uniform(a, b)` is `a / 100` (the gaps of real processes shrink to 0.2-0.6 s); `randint(a, b)` is `a`."""

    def uniform(self, a, b):
        return a / 100

    def randint(self, a, b):
        return a


def pacer(support, emit=no_emit, token=None, clock: FakeClock | None = None, rng: random.Random | None = None):
    """A SharedPacer on `clock` (default: one that starts at the real time), seeded for the same draws every time."""
    clock = clock or FakeClock(time.time())
    return SharedPacer(support, emit, token, sleep=clock.sleep, clock=clock.time, rng=rng or random.Random(1))


def fast_pacer(support, emit=no_emit, token=None):
    """`Services.pacer` for tests: the real pacing logic and file, on a clock that only moves when it waits, so no test
    waits for real."""
    return pacer(support, emit, token)


# --- what a spawned process of the cross-process tests runs (module level: `spawn` imports it by name) ---

def fail_once_in_a_library(root, support, queue) -> None:
    """One process of the streak test: opens the library, builds Qobuz's Budget on it, fails one request and saves."""
    from discjockey import library
    from discjockey.library import Paths
    from discjockey.pacing import Budget
    from discjockey.settings import Settings

    paths = Paths(Path(root), support=Path(support))
    state = library.load_state(paths)
    budget = Budget(state, lambda: library.save_state(paths, state), Settings(60))
    started_stopped = budget.stopped
    budget.failed("test: the request failed")
    queue.put((started_stopped, budget.stopped))


def stopped_in_a_library(root, support, queue) -> None:
    """A later process: whether Qobuz's Budget on the library starts paused."""
    from discjockey import library
    from discjockey.library import Paths
    from discjockey.pacing import Budget
    from discjockey.settings import Settings

    paths = Paths(Path(root), support=Path(support))
    budget = Budget(library.load_state(paths), lambda: None, Settings(60))
    queue.put((budget.stopped, budget.exhausted()))


def one_qobuz_download(support, hold_s, queue) -> None:
    """One process of the gap test: waits for its claim, 'downloads' for `hold_s` and ends it, with the shortest draws
    (a gap of 0.2 s). Puts (when it started, when it ended: just before it told the pacer)."""
    from discjockey.pacing import SharedPacer

    pacer = SharedPacer(Path(support), rng=ScaledRng())
    pacer.between_qobuz_downloads()
    started = time.time()
    time.sleep(hold_s)
    ended = time.time()
    pacer.downloaded("qobuz")
    queue.put((started, ended))
