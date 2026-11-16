"""T10, the locks table (issue 39 design §6.1, §13): for every built catalogue entry, the locks a call takes equal its
`locks` column. A fake lock layer replaces the four lock functions (`library.run_lock`, `library.support_lock`,
`rekordbox.lock.writer_lock`, `rekordbox.lock.reader_lock`) in every module that holds a name for them with a recorder
that notes the word and then takes the real lock. A command that lands later adds its driver below with its entry:
a built entry without a driver fails, so the column cannot be forgotten.

The probes (`jobs.lock_free`, the console watch) are not takes: they never hold a lock for work."""
from __future__ import annotations

import sys

import pytest

import hub_helpers
from hub_helpers import make_root, wait_job
from discjockey import library
from discjockey.hub import catalog
from discjockey.hub.api import CliApi
from discjockey.rekordbox import lock as rb_lock



class Recorder:
    def __init__(self):
        self.words: list[str] = []


@pytest.fixture
def fake_locks(monkeypatch):
    """The fake lock layer: every holder of a lock function (the defining module and each module that imported the
    name) gets the recorder in its place."""
    rec = Recorder()
    originals = {"run_lock": library.run_lock, "support_lock": library.support_lock,
                 "writer_lock": rb_lock.writer_lock, "reader_lock": rb_lock.reader_lock}
    words = {"run_lock": "library", "support_lock": "support", "writer_lock": "rekordbox_w",
             "reader_lock": "rekordbox_r"}

    def recording(name):
        real = originals[name]

        def take(*args, **kwargs):
            rec.words.append(words[name])
            return real(*args, **kwargs)
        take.__name__ = name
        return take

    fakes = {name: recording(name) for name in originals}
    for module in [m for n, m in list(sys.modules.items()) if n.startswith("discjockey") and m is not None]:
        for name, real in originals.items():
            if getattr(module, name, None) is real:
                monkeypatch.setattr(module, name, fakes[name])
    return rec


@pytest.fixture
def box(tmp_path, fake_locks):
    paths = make_root(tmp_path)
    events = hub_helpers.Recorder()
    api = CliApi(paths.support, events, hub_helpers.services())  # the command line's api: the cli_first methods too
    hub_helpers._MADE.append(api)  # conftest stops its jobs at teardown
    api._attach(paths)
    api._jobs.keep_awake = hub_helpers._no_awake
    api.lock_recorder = fake_locks  # a driver that sets something up first clears it before the call it measures
    return api, events, fake_locks


def taken_by(box, drive) -> frozenset[str]:
    api, events, rec = box
    rec.words.clear()
    drive(api, events)
    return frozenset(rec.words)


def _preview(api, rec):
    """`rekordbox preview --path` on a real file, against a fixture rekordbox library: its master.db is opened once."""
    from pathlib import Path
    from unittest import mock

    from rekordbox_helpers import make_master
    folder = api._paths.root / "rekordbox"
    make_master(folder, [])
    with mock.patch.dict("os.environ", {"DISCJOCKEY_REKORDBOX": str(folder)}):
        answer = api.rekordbox_preview(path=str(Path(__file__).parent / "fixtures" / "clicks-lame.mp3"))
    assert answer["ok"], answer


def _parked(api, rec, *, all_of_them: bool = False):
    """`upgrade` / `upgrade_all` on a song with a parked upgrade, against a fixture rekordbox library that does not hold the
    song (the batch opens it for writing: its master.db is the one thing a Same track changes there)."""
    from pathlib import Path
    from unittest import mock

    from rekordbox_helpers import make_master
    from discjockey.align import Alignment
    hub_helpers.make_root(api._paths.root, upgrade=True)
    folder = api._paths.root / "rekordbox"
    make_master(folder, [])
    api._svc.compare = lambda cur, new: Alignment("exact", 0, 0.0, 0.0, "matches exactly")
    api._svc.rekordbox_place = lambda: locate_in(folder)
    if all_of_them:
        answer = api.upgrade_all()
    else:  # with the plan of its dry run, as `--plan` runs it: that also reads rekordbox's state (`rekordbox_r`)
        plan_id = api.save_plan("upgrade apply", api.upgrade_preview(["t2"], "same_track"), "upgrade apply t2 --dry-run")
        answer = api.upgrade(["t2"], "same_track", plan_id)
    assert wait_job(api, rec, answer).ok


def _batch_of_one(api, rec, *, stopped: bool = False):
    """Batch 1 of the parked song `t2`, against a fixture rekordbox library: done (Same track), or `stopped` with its item
    still planned (what `batch resume` runs); the recorder is cleared, so a driver measures only the call after it."""
    from datetime import datetime

    from rekordbox_helpers import make_master
    from discjockey import batches, db
    from discjockey.align import Alignment
    hub_helpers.make_root(api._paths.root, upgrade=True)
    folder = api._paths.root / "rekordbox"
    make_master(folder, [])
    api._svc.compare = lambda cur, new: Alignment("exact", 0, 0.0, 0.0, "matches exactly")
    api._svc.rekordbox_place = lambda: locate_in(folder)
    if stopped:
        batch = batches.start(api._paths, [("t2", "same_track")], via="terminal")
        with db.connect(api._paths.db_file) as conn:
            db.set_aiff_batch(conn, batch, state="stopped", stop_reason="stop")
    else:
        assert wait_job(api, rec, api.upgrade_all()).ok
    api.lock_recorder.words.clear()


def _resume(api, rec):
    _batch_of_one(api, rec, stopped=True)
    assert wait_job(api, rec, api.batch_resume(1)).ok


def _batch_undo(api, rec):
    _batch_of_one(api, rec)
    assert wait_job(api, rec, api.batch_undo(1)).ok


def _a_backup(api, rec) -> str:
    """The id of a backup of the fixture rekordbox library (the one `rekordbox_place` answers); the recorder is cleared."""
    from rekordbox_helpers import make_master
    from discjockey.rekordbox import backup as rb_backup
    folder = api._paths.root / "rekordbox"
    make_master(folder, [])
    place = locate_in(folder)
    api._svc.rekordbox_place = lambda: place
    made = rb_backup.Backup.ensure(api._paths, place, dbid=None, batch_id=None, tracks=[])
    made.close(place)
    api.lock_recorder.words.clear()
    return made.id


def _restore(api, rec):
    backup = _a_backup(api, rec)
    assert wait_job(api, rec, api.rekordbox_restore(backup)).ok


def _after_new_track(api, rec):
    """A song whose upgrade was added as a new track (library lock only), then the recorder cleared: what follows is
    only the call a driver measures."""
    from discjockey.align import Alignment
    api._check_shown = False
    hub_helpers.make_root(api._paths.root, upgrade=True)
    api._svc.compare = lambda cur, new: Alignment("exact", 0, 0.0, 0.0, "matches exactly")
    assert wait_job(api, rec, api.upgrade(["t2"], "new_track")).ok
    api.lock_recorder.words.clear()


def _undo(api, rec):
    _after_new_track(api, rec)
    assert wait_job(api, rec, api.undo_upgrade(["t2"])).ok


def _checked(api, rec):
    _after_new_track(api, rec)
    assert wait_job(api, rec, api.rekordbox_checked(["t2"])).ok


def _discard(api, rec):
    api._check_shown = False  # the command line has no page whose picture of the track could be out of date
    hub_helpers.make_root(api._paths.root, upgrade=True)
    assert wait_job(api, rec, api.upgrade(["t2"], "discard")).ok


def locate_in(folder):
    from discjockey.rekordbox.locate import Place
    return Place(folder / "master.db", folder / "share", "override", None)


# one driver per built entry's method: it does what the command's method does, once
DRIVERS = {
    "rekordbox_preview": _preview,
    "batches": lambda api, rec: api.batches(),
    "batch_detail": lambda api, rec: api.batch_detail("moves:1"),
    "move_batches": lambda api, rec: api.move_batches(),
    "run": lambda api, rec: api.run("last"),
    "rekordbox_status": lambda api, rec: api.rekordbox_status(),
    "job_status": lambda api, rec: api.job_status(),
    "stop_refresh": lambda api, rec: api.stop_refresh(),
    "stop": lambda api, rec: api.stop(),
    "stop_sign_in": lambda api, rec: api.stop_sign_in(),
    "freshness": lambda api, rec: api.freshness(),
    "resolve": lambda api, rec: api.resolve("track", ["t1"]),
    "rescan_library": lambda api, rec: wait_job(api, rec, api.rescan_library()),
    "track": lambda api, rec: api.track("t2"),
    "todo": lambda api, rec: api.todo(),
    "find_tracks": lambda api, rec: api.find_tracks("naughty"),
    "select_listing": lambda api, rec: api.select_listing({"group": "all"}),  # a library listing takes no lock at all
    "upgrade_preview": lambda api, rec: api.upgrade_preview(["t2"]),
    "result_words": lambda api, rec: api.result_words("upgrade", {"results": [], "total": 0, "done": 0}),
    "upgrade": lambda api, rec: _parked(api, rec),
    "upgrade:upgrade discard": _discard,  # a driver per command where two entries of one method take different locks
    "upgrade_all": lambda api, rec: _parked(api, rec, all_of_them=True),
    "undo_upgrade": _undo,
    "undo_upgrade_preview": lambda api, rec: api.undo_upgrade_preview(["t2"]),
    "batch_resume": _resume,
    "batch_undo": _batch_undo,
    "batch_undo_preview": lambda api, rec: (_batch_of_one(api, rec), api.batch_undo_preview(1)),
    "rekordbox_checked": _checked,
    "rekordbox_backups": lambda api, rec: api.rekordbox_backups(),
    "rekordbox_restore": _restore,
    "rekordbox_restore_preview": lambda api, rec: api.rekordbox_restore_preview(_a_backup(api, rec)),
}
BUILT = [e for e in catalog.ENTRIES if e.planned is None]


@pytest.mark.parametrize("entry", BUILT, ids=lambda e: f"{e.method}:{' '.join(e.command)}")
def test_the_locks_a_built_entry_takes_are_its_locks_column(entry, box):
    if entry.kind in ("W", "dropped"):  # no command: nothing to take
        assert entry.locks == frozenset()
        return
    own = f"{entry.method}:{' '.join(entry.command)}"
    driver = DRIVERS.get(own) or DRIVERS.get(entry.method)
    assert driver, f"{entry.method} is built: add its driver to DRIVERS and its `locks` to the entry"
    assert taken_by(box, driver) == entry.locks


def test_a_driver_exists_only_for_a_built_entry():
    assert {d.split(":")[0] for d in DRIVERS} <= {e.method for e in BUILT}


# --- the design's table, for the kinds of job that exist in the engine today ---

def test_a_write_job_holds_the_library_and_takes_the_support_lock_only_for_its_save(box):
    assert taken_by(box, lambda api, rec: wait_job(api, rec, api.setup_skip_qobuz())) == {"library", "support"}


def test_a_brief_settings_save_outside_a_job_takes_the_library_briefly_and_the_support_lock(box):
    assert taken_by(box, lambda api, rec: api.setup_skip_import()) == {"library", "support"}


def test_a_support_only_job_takes_the_support_lock_and_no_library_lock(box):
    from tools_helpers import CheckRun, FakePyPI

    def update(api, rec):
        # a stubbed download of a newer yt-dlp: the lock is taken once it is in memory, to change tools/
        api._svc.fetch, api._svc.run = FakePyPI("2099.01.01", "0.8.1"), CheckRun()
        assert wait_job(api, rec, api.update_tools()).ok

    assert taken_by(box, update) == {"support"}
    assert taken_by(box, lambda api, rec: wait_job(api, rec, api.rollback_tools())) == {"support"}


def test_a_rekordbox_read_takes_the_shared_lock_and_nothing_else(box):
    assert taken_by(box, lambda api, rec: api.rekordbox_status()) == {"rekordbox_r"}
    assert taken_by(box, lambda api, rec: api.sidebar()) == frozenset()  # the count needs neither rekordbox nor a lock


def test_the_recorder_sees_a_lock_taken_by_name_in_another_module(fake_locks, tmp_path):
    from discjockey import rbstep
    from discjockey.library import Paths
    paths = Paths(tmp_path, support=tmp_path / "support")
    with rbstep.rekordbox_lock(paths, False):
        pass
    assert fake_locks.words == ["rekordbox_w"]
