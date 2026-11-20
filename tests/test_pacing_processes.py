"""The account protection across processes (issue 39 phase 2, V2.6): real spawned processes on one support folder."""
import multiprocessing
import time
from queue import Empty

import pytest

from discjockey import library
from discjockey.library import Paths
import pace_helpers

SPAWN = multiprocessing.get_context("spawn")
WAIT_S = 20


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.data.mkdir()
    p.support.mkdir()
    library.save_state(p, library.empty_state())
    return p


def run_processes(*jobs):
    """Starts each `(target, args)` as a spawned process at once, collects what each puts in the queue, and joins them all
    (a process that outlives its test is terminated)."""
    queue = SPAWN.Queue()
    procs = [SPAWN.Process(target=target, args=(*args, queue)) for target, args in jobs]
    try:
        for proc in procs:
            proc.start()
        results, deadline = [], time.monotonic() + WAIT_S
        while len(results) < len(procs):
            try:
                results.append(queue.get(timeout=0.2))
            except Empty:
                assert all(proc.exitcode in (None, 0) for proc in procs), "a process failed (its traceback is above)"
                assert time.monotonic() < deadline, "the processes did not answer in time"
        for proc in procs:
            proc.join(WAIT_S)
            assert proc.exitcode == 0
        return results
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(5)


def test_three_processes_that_each_fail_once_pause_qobuz_for_all_of_them(paths):
    seen = []
    for _ in range(3):  # in turn: each one loads what the one before saved
        [outcome] = run_processes((pace_helpers.fail_once_in_a_library, (str(paths.root), str(paths.support))))
        seen.append(outcome)
    assert seen == [(False, False), (False, False), (False, True)]
    [outcome] = run_processes((pace_helpers.stopped_in_a_library, (str(paths.root), str(paths.support))))
    assert outcome == (True, True)  # a fourth process starts paused
    assert library.load_state(paths)["qobuz_usage"]["streak"]["stopped"] is True


def test_two_processes_start_their_qobuz_downloads_a_gap_apart(paths):
    first, second = sorted(run_processes((pace_helpers.one_qobuz_download, (str(paths.support), 0.3)),
                                         (pace_helpers.one_qobuz_download, (str(paths.support), 0.3))))
    gap = 20 / 100  # the shortest draw of ScaledRng
    assert second[0] >= first[1] + gap  # the second claim waited for the first one's end, and then for the gap
