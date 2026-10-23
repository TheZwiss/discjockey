"""The window's page-server port (issue 17): its own, the same at every start, never another program's page."""
import json
import socket
import subprocess
import sys

import pytest

from discjockey.hub import window_port as wp


def seq(*ports):
    it = iter(ports)
    return lambda: next(it)


def saved(support):
    return json.loads((support / "window.json").read_text())["port"]


def test_the_first_start_picks_a_port_and_every_start_keeps_it(tmp_path):
    first = wp.window_port(tmp_path, free=lambda p: True, rand=seq(23456))
    assert (first.port, first.kept) == (23456, True) and saved(tmp_path) == 23456
    first.release()
    again = wp.window_port(tmp_path, free=lambda p: True, rand=seq(30000))
    assert (again.port, again.kept) == (23456, True)  # the saved settings keep their address
    again.release()


def test_a_saved_port_another_program_holds_is_replaced_and_the_new_one_kept(tmp_path):
    (tmp_path / "window.json").write_text('{"port": 23456}')
    got = wp.window_port(tmp_path, free=lambda p: p != 23456, rand=seq(23456, 24000))
    assert (got.port, got.kept) == (24000, True) and saved(tmp_path) == 24000
    got.release()


def test_a_second_window_takes_a_port_for_its_session_only(tmp_path):
    first = wp.window_port(tmp_path, free=lambda p: True, rand=seq(23456))
    second = wp.window_port(tmp_path, free=lambda p: p != 23456, rand=seq(25000))
    assert (second.port, second.kept, second.lock) == (25000, False, None)
    assert saved(tmp_path) == 23456  # the first window's settings stay where they are
    first.release()
    third = wp.window_port(tmp_path, free=lambda p: True, rand=seq(26000))
    assert (third.port, third.kept) == (23456, True)
    third.release()


@pytest.mark.parametrize("text", ["", "{", "[]", '{"port": "23456"}', '{"port": true}', '{"port": 80}',
                                  '{"port": 42001}', '{"port": 50000}', '{}'])
def test_a_broken_or_odd_window_file_gets_a_new_port(tmp_path, text):
    (tmp_path / "window.json").write_text(text)
    got = wp.window_port(tmp_path, free=lambda p: True, rand=seq(27000))
    assert (got.port, got.kept) == (27000, True) and saved(tmp_path) == 27000
    got.release()


def test_taken_ports_are_skipped_and_the_system_picks_when_none_is_free(tmp_path):
    got = wp.window_port(tmp_path, free=lambda p: p == 28000, rand=seq(23456, 23457, 28000))
    assert got.port == 28000
    got.release()
    (tmp_path / "window.json").unlink()
    last = wp.window_port(tmp_path, free=lambda p: False, rand=lambda: 23456)
    assert last.port > 0 and last.port != 23456
    last.release()


def test_an_unwritable_support_folder_still_opens_the_window(tmp_path):
    support = tmp_path / "support"
    support.write_text("a file where the folder should be")
    got = wp.window_port(support, free=lambda p: True, rand=seq(23456))
    assert (got.port, got.kept, got.lock) == (23456, False, None)


def test_a_port_another_program_listens_on_is_not_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as http.server's servers do
        other.bind(("127.0.0.1", 0))
        other.listen()
        assert not wp.port_free(other.getsockname()[1])


def test_a_port_nobody_uses_is_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert wp.port_free(port)


def test_the_real_random_pick_stays_in_the_range(tmp_path):
    got = wp.window_port(tmp_path)
    assert wp.LOW <= got.port < wp.HIGH and got.kept
    got.release()


def test_a_port_outside_our_range_is_used_but_not_kept(tmp_path):
    last = wp.window_port(tmp_path, free=lambda p: False, rand=lambda: 23456)
    assert not last.kept and not (tmp_path / "window.json").exists()
    last.release()


def test_a_window_file_that_cannot_be_written_still_gives_a_port(tmp_path):
    (tmp_path / "window.json").mkdir()  # a folder where the file should be: read and write both fail
    got = wp.window_port(tmp_path, free=lambda p: True, rand=seq(23456))
    assert (got.port, got.kept) == (23456, False) and got.lock is not None
    got.release()


def test_a_lock_file_left_by_a_dead_window_is_taken_over(tmp_path):
    (tmp_path / ".window.lock").write_text("")  # nobody holds it
    got = wp.window_port(tmp_path, free=lambda p: True, rand=seq(23456))
    assert got.kept and got.lock is not None
    got.release()


def test_a_lock_held_by_another_process_sends_this_window_to_its_own_port(tmp_path):
    code = ("import fcntl,sys,time;f=open(sys.argv[1],'a');fcntl.flock(f,fcntl.LOCK_EX);print('held',flush=True);"
            "sys.stdin.readline()")
    other = subprocess.Popen([sys.executable, "-c", code, str(tmp_path / ".window.lock")], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == "held"
        got = wp.window_port(tmp_path, free=lambda p: True, rand=seq(25000))
        assert (got.port, got.kept, got.lock) == (25000, False, None)
        assert not (tmp_path / "window.json").exists()
    finally:
        other.communicate("\n", timeout=10)


def test_a_program_listening_on_all_addresses_does_not_block_the_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        other.bind(("0.0.0.0", 0))
        other.listen()
        assert wp.port_free(other.getsockname()[1])  # our 127.0.0.1 socket is the more specific one and wins
