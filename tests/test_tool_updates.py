import errno
import fcntl
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from discjockey import tool_updates as tu, tools
from discjockey.events import Cancelled
from tools_helpers import CheckRun, FakePyPI, install_update, wheel, write_site, yt_dlp_files

REAL_HTTP_GET = tu.http_get  # conftest replaces tu.http_get in every test


@pytest.fixture
def env(tmp_path):
    """The built-in yt-dlp is 2026.10.21 and this process runs it; the support folder has a space in its path."""
    site = write_site(tmp_path / "site", yt="2026.10.21")
    builtin = (site / "yt_dlp").resolve()
    return SimpleNamespace(support=tmp_path / "Application Support" / "Discjockey", builtin=builtin)


def update(env, pypi, *, run=None, running=None, check=None):
    return tu.update(env.support, fetch=pypi, run=run or CheckRun(), check=check,
                     running=running or env.builtin, builtin=env.builtin)


def rollback(env, running=None):
    return tu.rollback(env.support, running=running or env.builtin, builtin=env.builtin)


def names(env) -> list[str]:
    return sorted(p.name for p in tools.tools_root(env.support).iterdir())


def status(env, running=None) -> dict:
    return tu.status(env.support, running=running or env.builtin, builtin=env.builtin)["yt-dlp"]


# --- update ---

def test_an_update_installs_the_newest_and_points_current_at_it(env):
    pypi, run = FakePyPI("2026.10.28", "0.8.1"), CheckRun()
    assert update(env, pypi, run=run) == ({"yt-dlp": "2026.10.21"}, {"yt-dlp": "2026.10.28"}, True)
    folder = tools.current_folder(env.support)
    assert folder.name == "2026.10.28" and tools.folder_version(folder) == "2026.10.28"
    assert tools.package_version(folder / "yt_dlp_ejs") == "0.8.1"
    assert (folder / "yt_dlp-2026.10.28.dist-info" / "METADATA").is_file()
    assert not (folder / "yt_dlp-2026.10.28.data").exists()  # no scripts or data files
    assert names(env) == ["2026.10.28", "current"]  # no .partial-* left
    assert run.folders[0].name == ".partial-2026.10.28"  # tested before it was used
    assert "https://pypi.org/pypi/yt-dlp-ejs/0.8.1/json" in pypi.requested  # the version yt-dlp pins


def test_already_the_newest_downloads_nothing(env):
    pypi = FakePyPI("2026.10.21")
    assert update(env, pypi) == ({"yt-dlp": "2026.10.21"}, {"yt-dlp": "2026.10.21"}, False)
    assert pypi.requested == ["https://pypi.org/pypi/yt-dlp/json"]
    assert not tools.tools_root(env.support).exists()


def test_leading_zeros_are_the_same_version(tmp_path):
    site = write_site(tmp_path / "site", yt="2025.01.15")
    builtin = (site / "yt_dlp").resolve()
    before, after, restart = tu.update(tmp_path / "support", fetch=FakePyPI("2025.1.15"), run=CheckRun(),
                                       running=builtin, builtin=builtin)
    assert restart is False and not (tmp_path / "support" / "tools").exists()


def test_a_newer_update_waiting_for_a_reopen_is_not_fetched_again(env):
    update(env, FakePyPI("2026.10.28"))
    pypi = FakePyPI("2026.10.28")
    assert update(env, pypi) == ({"yt-dlp": "2026.10.28"}, {"yt-dlp": "2026.10.28"}, True)
    assert pypi.requested == ["https://pypi.org/pypi/yt-dlp/json"]


@pytest.mark.parametrize("pypi,message", [
    (lambda url: (_ for _ in ()).throw(OSError("offline")), tu.OFFLINE),
    (lambda url: b"<html>not json</html>", tu.BAD_ANSWER),
    (FakePyPI(damage="yt"), tu.DAMAGED),
    (FakePyPI(damage="ejs"), tu.DAMAGED),
    (lambda url: (_ for _ in ()).throw(tu.HttpStatus(503, url)), tu.SERVER_ERROR),
    (FakePyPI(pure=False), tu.NO_WHEEL),
])
def test_a_failed_download_changes_nothing(env, pypi, message):
    old = install_update(env.support, "2026.10.24")
    with pytest.raises(tu.ToolsError) as e:
        update(env, pypi)
    assert str(e.value) == message and e.value.kind == "failed"
    assert tools.current_folder(env.support) == old and names(env) == ["2026.10.24", "current"]


def test_a_failed_check_keeps_the_tools_in_use(env):
    old = install_update(env.support, "2026.10.24")
    with pytest.raises(tu.ToolsError) as e:
        update(env, FakePyPI("2026.10.28"), run=CheckRun(ok=False))
    assert str(e.value) == tu.CHECK_FAILED
    assert tools.current_folder(env.support) == old and names(env) == ["2026.10.24", "current"]


def test_a_check_that_reports_another_version_is_a_failed_check(env):
    def liar(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout='{"yt-dlp": "2026.10.21", "yt-dlp-ejs": "0.8.1"}\n', stderr="")
    with pytest.raises(tu.ToolsError, match="didn't pass its test"):
        update(env, FakePyPI("2026.10.28"), run=liar)
    assert tools.current_folder(env.support) is None


def test_without_an_exact_pin_the_newest_yt_dlp_ejs_is_used(env):
    pypi = FakePyPI("2026.10.28", "0.9.0", pin=False)
    update(env, pypi)
    assert "https://pypi.org/pypi/yt-dlp-ejs/json" in pypi.requested
    assert tools.package_version(tools.current_folder(env.support) / "yt_dlp_ejs") == "0.9.0"


def test_stop_while_testing_changes_nothing(env):
    old = install_update(env.support, "2026.10.24")

    def stopped(cmd, **kw):
        raise Cancelled()
    with pytest.raises(Cancelled):
        update(env, FakePyPI("2026.10.28"), run=stopped)
    assert tools.current_folder(env.support) == old and names(env) == ["2026.10.24", "current"]


def test_leftovers_of_an_interrupted_update_are_cleared(env):
    leftover = tools.tools_root(env.support) / ".partial-2026.10.27"
    (leftover / "yt_dlp").mkdir(parents=True)
    update(env, FakePyPI("2026.10.28"))
    assert names(env) == ["2026.10.28", "current"]


def test_an_update_repairs_a_broken_current(env):
    folder = install_update(env.support, "2026.10.24")
    (folder / "yt_dlp" / "version.py").unlink()  # half deleted by hand
    update(env, FakePyPI("2026.10.28"))
    assert tools.current_folder(env.support).name == "2026.10.28"
    assert names(env) == ["2026.10.28", "current"]  # the broken folder is gone too


def test_a_wheel_reaching_outside_its_folder_is_damaged(tmp_path):
    with pytest.raises(tu.ToolsError, match="damaged"):
        tu.unpack(wheel({"../evil.py": "x"}), tmp_path / "into")
    with pytest.raises(tu.ToolsError, match="damaged"):
        tu.unpack(b"not a zip", tmp_path / "into")
    tu.unpack(wheel({**yt_dlp_files("2026.10.28"), "bin/yt-dlp": "#!/bin/sh"}), tmp_path / "ok")
    assert (tmp_path / "ok" / "yt_dlp" / "version.py").is_file() and not (tmp_path / "ok" / "bin").exists()


@pytest.mark.parametrize("requires,pin", [
    (['yt-dlp-ejs==0.8.0; extra == "default"'], "0.8.0"),
    (["yt-dlp-ejs==0.8.0 ; extra == 'default'"], "0.8.0"),
    (['yt-dlp-ejs==0.8.0; extra == "pin"'], None),
    (['yt-dlp-ejs>=0.8; extra == "default"'], None),
    ([], None),
    (None, None),
])
def test_the_pinned_yt_dlp_ejs(requires, pin):
    assert tu.ejs_pin({"requires_dist": requires}) == pin


# --- one previous folder, never the one in use ---

def test_one_previous_folder_is_kept(env):
    update(env, FakePyPI("2026.10.28"))
    update(env, FakePyPI("2026.11.02"))
    assert names(env) == ["2026.10.28", "2026.11.02", "current"]
    update(env, FakePyPI("2026.11.09"))
    assert names(env) == ["2026.11.02", "2026.11.09", "current"]


def test_the_folder_in_use_is_never_deleted(env):
    update(env, FakePyPI("2026.10.28"))
    running = tools.current_folder(env.support) / "yt_dlp"  # reopened: this process runs 2026.10.28
    update(env, FakePyPI("2026.11.02"), running=running)
    update(env, FakePyPI("2026.11.09"), running=running)  # two updates without reopening
    assert names(env) == ["2026.10.28", "2026.11.02", "2026.11.09", "current"]
    running = tools.current_folder(env.support) / "yt_dlp"  # reopened on 2026.11.09
    update(env, FakePyPI("2026.11.16"), running=running)
    assert names(env) == ["2026.11.09", "2026.11.16", "current"]


def hold_like_another_process(folder):
    """What a hub running yt-dlp from `folder` holds (its own open file, so it conflicts with ours)."""
    fd = os.open(folder / tools.IN_USE, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_SH)
    return fd


def test_a_folder_another_process_holds_is_never_pruned(env):
    update(env, FakePyPI("2026.10.28"))
    held = tools.current_folder(env.support)
    fd = hold_like_another_process(held)  # an idle hub runs 2026.10.28
    try:
        update(env, FakePyPI("2026.11.02"))
        update(env, FakePyPI("2026.11.09"))  # this process runs the built-in copy, so only the lock protects it
        assert names(env) == ["2026.10.28", "2026.11.02", "2026.11.09", "current"]
    finally:
        os.close(fd)  # the hub quit
    update(env, FakePyPI("2026.11.16"))
    assert names(env) == ["2026.11.09", "2026.11.16", "current"]


def test_going_back_keeps_a_folder_another_process_holds(env):
    update(env, FakePyPI("2026.10.28"))
    update(env, FakePyPI("2026.11.02"))
    fd = hold_like_another_process(tools.current_folder(env.support))
    try:
        rollback(env)
        assert names(env) == ["2026.10.28", "2026.11.02", "current"]
    finally:
        os.close(fd)


def test_hold_in_use_takes_a_shared_lock_for_the_life_of_the_process(tmp_path, monkeypatch):
    held = []
    monkeypatch.setattr(tools, "_held", held)
    folder = tmp_path / "2026.10.28"
    folder.mkdir()
    (folder / "yt_dlp").mkdir()
    tools.hold_in_use(folder)
    tools.hold_in_use(folder)  # shared: two holders are fine
    try:
        assert tools.remove_unless_in_use(folder) is False and (folder / "yt_dlp").is_dir()
    finally:
        for fd in held:
            os.close(fd)
    assert tools.remove_unless_in_use(folder) is True and not folder.exists()


def test_a_folder_nobody_holds_is_removed_and_a_missing_one_is_fine(tmp_path):
    folder = tmp_path / "2026.10.28"
    (folder / "yt_dlp").mkdir(parents=True)
    assert tools.remove_unless_in_use(folder) is True and not folder.exists()
    assert tools.remove_unless_in_use(folder) is True


def test_an_update_leaves_byte_code_for_the_next_start(env):
    update(env, FakePyPI("2026.10.28", "0.8.1"))
    folder = tools.current_folder(env.support)
    assert list((folder / "yt_dlp").rglob("*.pyc")) and list((folder / "yt_dlp_ejs").rglob("*.pyc"))


# --- rollback ---

def test_go_back_to_the_built_in_copy(env):
    update(env, FakePyPI("2026.10.28"))
    assert rollback(env) == ({"yt-dlp": "2026.10.28"}, {"yt-dlp": "2026.10.21"}, False)
    assert tools.current_folder(env.support) is None and names(env) == []


def test_go_back_to_the_previous_update(env):
    update(env, FakePyPI("2026.10.28"))
    update(env, FakePyPI("2026.11.02"))
    assert rollback(env) == ({"yt-dlp": "2026.11.02"}, {"yt-dlp": "2026.10.28"}, True)
    assert tools.current_folder(env.support).name == "2026.10.28" and names(env) == ["2026.10.28", "current"]


def test_going_back_keeps_the_folder_in_use_on_disk(env):
    update(env, FakePyPI("2026.10.28"))
    update(env, FakePyPI("2026.11.02"))
    running = tools.current_folder(env.support) / "yt_dlp"
    assert rollback(env, running=running)[2] is True
    assert names(env) == ["2026.10.28", "2026.11.02", "current"]
    assert tools.current_folder(env.support).name == "2026.10.28"


def test_nothing_to_go_back_to(env):
    with pytest.raises(tu.ToolsError) as e:
        rollback(env)
    assert str(e.value) == tu.NOTHING_TO_UNDO and e.value.kind == "refused"
    install_update(env.support, "2026.10.14")  # older than the built-in copy, which wins anyway
    with pytest.raises(tu.ToolsError):
        rollback(env)


# --- status (Settings → This Mac) ---

def test_status_with_only_the_built_in_copy(env):
    assert status(env) == {"version": "2026.10.21", "source": "built_in", "waiting": None, "previous": None}


def test_status_after_an_update_before_reopening(env):
    update(env, FakePyPI("2026.10.28"))
    assert status(env) == {"version": "2026.10.21", "source": "built_in", "waiting": "2026.10.28",
                           "previous": "2026.10.21"}


def test_status_after_reopening(env):
    update(env, FakePyPI("2026.10.28"))
    running = tools.current_folder(env.support) / "yt_dlp"
    assert status(env, running) == {"version": "2026.10.28", "source": "updated", "waiting": None,
                                    "previous": "2026.10.21"}


def test_status_when_the_app_brought_a_newer_one(env):
    install_update(env.support, "2026.10.14")
    assert status(env) == {"version": "2026.10.21", "source": "built_in", "waiting": None, "previous": None}


def test_streamrip_is_always_built_in(env):
    s = tu.status(env.support, running=env.builtin, builtin=env.builtin)["streamrip"]
    assert s["version"] and s["source"] == "built_in" and s["waiting"] is None and s["previous"] is None


def test_current_status_reads_this_process(tmp_path):
    import yt_dlp.version
    s = tu.current_status(tmp_path / "support")["yt-dlp"]
    assert s == {"version": yt_dlp.version.__version__, "source": "built_in", "waiting": None, "previous": None}


def test_update_lines():
    assert tu.update_line({"yt-dlp": "2026.10.21"}, {"yt-dlp": "2026.10.28"}) == "yt-dlp 2026.10.21 -> 2026.10.28"
    assert tu.update_line({"yt-dlp": "2026.10.21"}, {"yt-dlp": "2026.10.21"}) == \
        "yt-dlp 2026.10.21 is already the newest."
    assert tu.update_line({"yt-dlp": None}, {"yt-dlp": "2026.10.28"}) == "yt-dlp updated to 2026.10.28"


# --- damaged downloads, disk problems, Stop ---

def test_a_bad_hash_never_unpacks_anything(env, monkeypatch):
    calls = []
    monkeypatch.setattr(tu, "unpack", lambda *a: calls.append(a))
    for damage in ("yt", "ejs"):
        with pytest.raises(tu.ToolsError, match="damaged"):
            update(env, FakePyPI(damage=damage))
    assert calls == [] and not tools.tools_root(env.support).exists()


def test_a_wheel_that_breaks_while_unpacking_is_damaged(tmp_path):
    good = wheel({**yt_dlp_files("2026.10.28")})
    marker = b"__version__"
    flipped = good.replace(marker, b"__versiOn__")  # same length: the stored file no longer matches its CRC
    assert flipped != good
    with pytest.raises(tu.ToolsError) as e:
        tu.unpack(flipped, tmp_path / "into")
    assert str(e.value) == tu.DAMAGED


@pytest.mark.parametrize("error,words", [
    (OSError(errno.ENOSPC, "No space left on device"), "the disk is full"),
    (OSError(errno.EACCES, "Permission denied"), "isn't allowed to write"),
    (OSError(errno.EEXIST, "File exists"), "the disk refused"),
    (OSError("odd"), "the disk refused"),
])
def test_a_disk_problem_is_said_in_plain_words_and_changes_nothing(env, monkeypatch, error, words):
    old = install_update(env.support, "2026.10.24")

    def refuse(*a, **k):
        raise error
    monkeypatch.setattr(tu.os, "rename", refuse)
    with pytest.raises(tu.ToolsError) as e:
        update(env, FakePyPI("2026.10.28"))
    message = str(e.value)
    assert words in message and message.endswith("Nothing was changed.") and e.value.kind == "failed"
    assert str(error.strerror or error) not in message
    assert tools.current_folder(env.support) == old and names(env) == ["2026.10.24", "current"]


def test_a_disk_problem_while_going_back_is_a_plain_failure(env, monkeypatch):
    update(env, FakePyPI("2026.10.28"))
    update(env, FakePyPI("2026.11.02"))

    def refuse(*a, **k):
        raise OSError(errno.EEXIST, "File exists")
    monkeypatch.setattr(tu.os, "symlink", refuse)
    with pytest.raises(tu.ToolsError) as e:
        rollback(env)
    assert "File exists" not in str(e.value) and tools.current_folder(env.support).name == "2026.11.02"


def test_the_unpacked_files_are_synced_before_current_moves(env, monkeypatch):
    order = []
    monkeypatch.setattr(tu, "_sync_to_disk", lambda folder: order.append(("sync", folder.name)))
    real = tu._point_current
    monkeypatch.setattr(tu, "_point_current", lambda support, folder: (order.append(("point", folder.name)),
                                                                       real(support, folder)))
    update(env, FakePyPI("2026.10.28"))
    assert order == [("sync", ".partial-2026.10.28"), ("point", "2026.10.28")]


def test_sync_to_disk_walks_files_and_folders(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.py").write_text("x")
    tu._sync_to_disk(tmp_path)  # must not raise


def _fake_check_command(monkeypatch, code):
    monkeypatch.setattr(tools, "check_command", lambda folder: ([sys.executable, "-c", code], None))


def test_the_real_check_process_reports_its_output(tmp_path, monkeypatch):
    out = '{"yt-dlp": "2026.10.28", "yt-dlp-ejs": "0.8.1"}'
    _fake_check_command(monkeypatch, f"print('noise'); print({out!r})")
    tu._run_check(subprocess.run, tmp_path, {"yt-dlp": "2026.10.28", "yt-dlp-ejs": "0.8.1"}, lambda: None)
    _fake_check_command(monkeypatch, "import sys; sys.exit(3)")
    with pytest.raises(tu.ToolsError, match="didn't pass its test"):
        tu._run_check(subprocess.run, tmp_path, {"yt-dlp": "2026.10.28"}, lambda: None)


def test_stop_ends_the_check_process_and_what_it_started(tmp_path, monkeypatch):
    pids = tmp_path / "pids"
    code = ("import os, subprocess, sys, time\n"
            "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pids)!r}, 'w').write(f'{{os.getpid()}} {{kid.pid}}')\n"
            "time.sleep(60)\n")
    _fake_check_command(monkeypatch, code)
    started, asked = time.monotonic(), []

    def stop_once_started():
        asked.append(1)
        if pids.exists() and pids.read_text().count(" ") == 1:
            raise Cancelled()
    with pytest.raises(Cancelled):
        tu._run_check(subprocess.run, tmp_path, {"yt-dlp": "x"}, stop_once_started)
    assert time.monotonic() - started < 10
    for pid in map(int, pids.read_text().split()):
        for _ in range(50):  # the kill is a signal: give the system a moment to finish the process
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"process {pid} is still alive after Stop")


def test_the_check_has_a_time_limit(tmp_path, monkeypatch):
    _fake_check_command(monkeypatch, "import time; time.sleep(60)")
    monkeypatch.setattr(tu, "CHECK_TIMEOUT_S", 0.5)
    with pytest.raises(tu.ToolsError, match="didn't pass its test"):
        tu._run_check(subprocess.run, tmp_path, {"yt-dlp": "x"}, lambda: None)


def test_http_get_tells_an_error_status_from_no_answer(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: SimpleNamespace(status_code=404, content=b""))
    with pytest.raises(tu.HttpStatus) as e:
        REAL_HTTP_GET("https://pypi.org/pypi/yt-dlp/json")
    assert e.value.status == 404
    monkeypatch.setattr(requests, "get", lambda url, **kw: SimpleNamespace(status_code=200, content=b"ok"))
    assert REAL_HTTP_GET("https://x") == b"ok"


def test_an_archive_that_unpacks_to_too_much_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(tu, "MAX_UNPACKED_BYTES", 1000)
    with pytest.raises(tu.ToolsError) as e:
        tu.unpack(wheel({"yt_dlp/big.py": "x" * 2000}), tmp_path / "into")
    assert str(e.value) == tu.DAMAGED and not (tmp_path / "into").exists()
    tu.unpack(wheel({"yt_dlp/small.py": "x" * 900, "bin/ignored": "y" * 5000}), tmp_path / "ok")  # only what is kept counts
    assert (tmp_path / "ok" / "yt_dlp" / "small.py").is_file()


@pytest.mark.parametrize("code,fails", [(errno.EINVAL, False), (errno.ENOTSUP, False), (errno.EIO, True)])
def test_a_folder_that_cannot_be_synced_is_no_failure_but_a_real_error_is(tmp_path, monkeypatch, code, fails):
    (tmp_path / "f.py").write_text("x")
    real_fsync = os.fsync

    def fsync(fd):
        if os.path.isdir(f"/dev/fd/{fd}") or os.fstat(fd).st_mode & 0o170000 == 0o040000:
            raise OSError(code, "no")
        real_fsync(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr("fcntl.fcntl", lambda fd, op: (_ for _ in ()).throw(OSError(code, "no")))
    if fails:
        with pytest.raises(OSError):
            tu._sync_to_disk(tmp_path)
    else:
        tu._sync_to_disk(tmp_path)
