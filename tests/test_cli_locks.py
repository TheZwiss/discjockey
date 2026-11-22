"""T10, the locks table (issue 39 design §6.1, §13): for every built catalogue entry, the locks a call takes equal its
`locks` column. A fake lock layer replaces the four lock functions (`library.run_lock`, `library.support_lock`,
`rekordbox.lock.writer_lock`, `rekordbox.lock.reader_lock`) in every module that holds a name for them with a recorder
that notes the word and then takes the real lock. A command that lands later adds its driver below with its entry:
a built entry without a driver fails, so the column cannot be forgotten.

The probes (`jobs.lock_free`, the console watch) are not takes: they never hold a lock for work."""
from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

import pytest

import hub_helpers
from hub_helpers import wait_job
from discjockey import library
from discjockey.hub import catalog, registry
from discjockey.hub.api import CliApi
from discjockey.rekordbox import lock as rb_lock


CLICKS = Path(__file__).parent / "fixtures" / "clicks-lame.mp3"  # the one real audio file


class Recorder:
    """`words` are the takes in the order the lock functions were called; `events` are the holds as they open and close:
    `("take", word, thread)` when the lock is held, `("release", word, thread)` when the block ends."""

    def __init__(self):
        self.words: list[str] = []
        self.events: list[tuple[str, str, int]] = []


class Held:
    """The context manager a lock function returned, noting when its hold opens and when it ends."""

    def __init__(self, inner, rec: Recorder, word: str):
        self.inner, self.rec, self.word = inner, rec, word

    def __enter__(self):
        value = self.inner.__enter__()
        self.rec.events.append(("take", self.word, threading.get_ident()))
        return value

    def __exit__(self, *exc):
        try:
            return self.inner.__exit__(*exc)
        finally:
            self.rec.events.append(("release", self.word, threading.get_ident()))


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
            return Held(real(*args, **kwargs), rec, words[name])
        take.__name__ = name
        return take

    fakes = {name: recording(name) for name in originals}
    for module in [m for n, m in list(sys.modules.items()) if n.startswith("discjockey") and m is not None]:
        for name, real in originals.items():
            if getattr(module, name, None) is real:
                monkeypatch.setattr(module, name, fakes[name])
    return rec


@pytest.fixture
def box(tmp_path, fake_locks, monkeypatch):
    hub_helpers.fake_import(monkeypatch)  # `folder add`'s import reads no real audio
    paths = hub_helpers.music_root(tmp_path)  # beside it, the folders `folder add` watches
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


def _plan(api, rec):
    """`sync plan` with a stored read, so there is a plan to derive (an unread library answers before it looks at anything)."""
    from hub_helpers import ID1, ID2, TRACKS, store_sync_read

    from discjockey.models import FetchedPlaylist, PlaylistLine
    store_sync_read(api._paths, [FetchedPlaylist(PlaylistLine("Hard_Bounce", ID1, 2), TRACKS[ID1], []),
                                 FetchedPlaylist(PlaylistLine("Powertrance", ID2, 3), TRACKS[ID2], [])])
    api.lock_recorder.words.clear()
    assert api.sync_preview("pegassi")["groups"]


def _spectrum(api, rec):
    """`track spectrum` on `t2`, whose file is made a real recording: it decodes the file and opens no library."""
    shutil.copyfile(CLICKS, api._paths.root / hub_helpers.LOSSY)
    assert api.spectrum("t2")["ok"]


def _parked(api, rec, *, all_of_them: bool = False, phase: str | None = None):
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
    if phase:  # the phase asks rekordbox's library only for a file that is not an AIFF (`auto_upgrade.plan`)
        from discjockey import library
        state = library.load_state(api._paths)
        old = api._paths.root / state["tracks"]["t2"]["path"]
        mp3 = old.with_suffix(".mp3")
        old.rename(mp3)
        state["tracks"]["t2"]["path"] = str(mp3.relative_to(api._paths.root))
        library.save_state(api._paths, state)
    if phase == "run":  # the sync's last phase alone: the plan reads rekordbox, the batch writes it
        answer = api.auto_upgrade_run()
    elif phase == "preview":  # its dry run: a read, no job
        assert api.auto_upgrade_preview()["ok"]
        return
    elif all_of_them:
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
    with rb_backup.master.open_read(place, False) as m:
        dbid = m.dbid
    made = rb_backup.Backup.ensure(api._paths, place, dbid=dbid, batch_id=None, tracks=[])
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
    hub_helpers.make_root(api._paths.root, upgrade=True)
    assert wait_job(api, rec, api.upgrade(["t2"], "discard")).ok


def _own_song(api, kinds=("mp3",)):
    """A library of own songs (`batch_helpers.make_own_lib`) and a second api attached to it, with the events recorder its
    jobs report to: what `aiff convert | rename` work on. The lock recorder sees every api."""
    from batch_helpers import make_own_lib
    from convert_helpers import EXACT
    folder = api._paths.root / "own-library"
    folder.mkdir(exist_ok=True)
    with pytest.MonkeyPatch.context() as mp:
        lib = make_own_lib(folder, mp, list(kinds))
    events = hub_helpers.Recorder()
    own = CliApi(lib.paths.support, events, hub_helpers.services(
        rekordbox_place=lambda: lib.place, rekordbox_running=lambda: False, compare=lambda a, b: EXACT))
    hub_helpers._MADE.append(own)
    own._attach(lib.paths)
    own._jobs.keep_awake = hub_helpers._no_awake
    return lib, own, events


def _aiff_run(method: str):
    """`convert` / `rename` / `make_aiff` with the plan of their dry run, as `--plan` runs them: the plan is read (the
    shared `rekordbox.lock`, only while master.db is open), then the batch holds the library and rekordbox's writer."""
    def drive(api, rec):
        lib, own, events = _own_song(api, ("mp3",) if method == "convert" else ("clean",))  # a Convert; a Rename's item
        scope = {"kind": "lossless", "view": "all", "key": None} if method == "make_aiff" else {
            "kind": "tracks", "tracks": lib.tracks}
        plan_id = own.save_plan("aiff convert", own.aiff_plan(scope), "aiff convert")
        args = {"convert": (lib.tracks, "library", plan_id), "rename": (lib.tracks, plan_id),
                "make_aiff": (scope, plan_id)}[method]
        assert wait_job(own, events, getattr(own, method)(*args)).ok
    return drive


def _aiff_plan(api, rec):
    lib, own, events = _own_song(api)
    assert own.aiff_plan({"kind": "lossless", "view": "all", "key": None})["ok"]


def locate_in(folder):
    from discjockey.rekordbox.locate import Place
    return Place(folder / "master.db", folder / "share", "override", None)


# one driver per built entry's method: it does what the command's method does, once
def _watch(api, rec):
    """`folder add` on a folder of three audio files (the import's readers faked), through to the end of its job."""
    import hub_helpers
    from pathlib import Path
    folder = hub_helpers.import_folder(Path(api._paths.root).parent, 3)
    answer = api.add_watched_folder(str(folder))
    assert wait_job(api, rec, answer).ok
    return folder


def _watched_id(api, rec) -> int:
    """The id of a watched import folder made before the call that is measured (its locks are not the call's)."""
    import hub_helpers
    from pathlib import Path
    folder = hub_helpers.import_folder(Path(api._paths.root).parent, 1, name="Measured")
    assert wait_job(api, rec, api.add_watched_folder(str(folder))).ok
    rec_words = getattr(api, "lock_recorder", None)
    if rec_words is not None:
        rec_words.words.clear()
    return next(r["id"] for r in api.watched_folders()["folders"] if r["kind"] == "import")


def _a_job(api) -> str:
    """The id of a job in the registry (a read of its events is the driver of `job_events`)."""
    roots = {"music": None, "support": None, "rekordbox": None, "rekordbox_share": None, "sandbox": None}
    return registry.Registry(api._support.support).create("sync", "sync run", {}, "terminal", roots).id


def _check_a_link(api):
    """`playlist check <link>` against the hub's SoundCloud stub (in place for this one call only): it reads the link's
    playlist and stores the read, and takes no lock."""
    import pytest
    from test_hub_api_playlists import SC_SET, fake_soundcloud
    with pytest.MonkeyPatch.context() as patch:
        fake_soundcloud(patch)
        assert api.add_playlist(SC_SET)["ok"]


def _open_buy_list(api) -> dict:
    """`open report not-lossless --print` on a library that has a buy list."""
    api._paths.not_lossless_md.write_text("Songs to buy\n")
    return _opened(api.open_report("not-lossless", print_only=True))


def _opened(answer: dict) -> dict:
    """An opener's answer, which must be `Opened` (a refusal would measure none of the success path's locks)."""
    assert answer["ok"] and answer["opened"] is False, answer
    return answer


DRIVERS = {
    "rekordbox_preview": _preview,
    "batches": lambda api, rec: api.batches(),
    "batch_detail": lambda api, rec: api.batch_detail("moves:1"),
    "move_batches": lambda api, rec: api.move_batches(),
    "run": lambda api, rec: api.run("last"),
    "runs": lambda api, rec: api.runs(),  # the stored reports: no lock
    "library": lambda api, rec: api.library("all", None, "naughty"),
    "sidebar": lambda api, rec: api.sidebar(),
    "sync_preview": _plan,
    "watched_folders": lambda api, rec: api.watched_folders(),
    "check_import_folder": lambda api, rec: api.check_import_folder(str(api._paths.root / "Crate")),
    "spectrum": _spectrum,  # a file's own samples: not master.db
    "rekordbox_status": lambda api, rec: api.rekordbox_status(),
    "job_status": lambda api, rec: api.job_status(),
    "job_events": lambda api, rec: api.job_events(_a_job(api)),
    "stop_refresh": lambda api, rec: api.stop_refresh(),
    "stop": lambda api, rec: api.stop(),
    "stop_sign_in": lambda api, rec: api.stop_sign_in(),
    "freshness": lambda api, rec: api.freshness(),
    "resolve": lambda api, rec: api.resolve("track", ["t1"]),
    "rescan_library": lambda api, rec: wait_job(api, rec, api.rescan_library()),
    "fill_facts": lambda api, rec: wait_job(api, rec, api.fill_facts()),
    "facts_preview": lambda api, rec: api.facts_preview(),
    "track": lambda api, rec: api.track("t2"),
    "todo": lambda api, rec: api.todo(),
    "find_tracks": lambda api, rec: api.find_tracks("naughty"),
    "select_listing": lambda api, rec: api.select_listing({"group": "all"}),  # a library listing takes no lock at all
    "upgrade_preview": lambda api, rec: api.upgrade_preview(["t2"]),
    "result_words": lambda api, rec: api.result_words("upgrade", {"results": [], "total": 0, "done": 0}),
    "upgrade": lambda api, rec: _parked(api, rec),
    "upgrade:upgrade discard": _discard,  # a driver per command where two entries of one method take different locks
    "upgrade_all": lambda api, rec: _parked(api, rec, all_of_them=True),
    "auto_upgrade_run": lambda api, rec: _parked(api, rec, phase="run"),
    "auto_upgrade_preview": lambda api, rec: _parked(api, rec, phase="preview"),
    "undo_upgrade": _undo,
    "undo_upgrade_preview": lambda api, rec: api.undo_upgrade_preview(["t2"]),
    "batch_resume": _resume,
    "batch_undo": _batch_undo,
    "batch_undo_preview": lambda api, rec: (_batch_of_one(api, rec), api.batch_undo_preview(1)),
    "rekordbox_checked": _checked,
    "rekordbox_backups": lambda api, rec: api.rekordbox_backups(),
    "rekordbox_restore": _restore,
    "rekordbox_restore_preview": lambda api, rec: api.rekordbox_restore_preview(_a_backup(api, rec)),
    "convert": _aiff_run("convert"),
    "rename": _aiff_run("rename"),
    "make_aiff": _aiff_run("make_aiff"),
    "settings_view": lambda api, rec: api.settings_view(),  # a read of the support folder's file: no lock
    "set_auto_upgrade": lambda api, rec: wait_job(api, rec, api.set_auto_upgrade(False)),
    "sync_scope": lambda api, rec: api.sync_scope(),  # a read of the support folder's file: no lock
    "set_sync_scope": lambda api, rec: wait_job(api, rec, api.set_sync_scope([], ["kind:weekly"])),  # `sync scope on|off`
    "add_watched_folder": lambda api, rec: _watch(api, rec),
    "removal_preview": lambda api, rec: api.removal_preview(_watched_id(api, rec)),
    "missing_files": lambda api, rec: wait_job(api, rec, api.missing_files(["t3"], "download_again")),  # a skipped song: the job still takes its lock
    "missing_files_preview": lambda api, rec: api.missing_files_preview(["t2"], "download_again"),
    "remove_watched_folder": lambda api, rec: wait_job(api, rec, api.remove_watched_folder(_watched_id(api, rec))),
    "tidy_preview": lambda api, rec: api.tidy_preview(),  # `tidy run --dry-run`: the records, no lock
    "undo_preview": lambda api, rec: api.undo_preview(1),  # `batch undo moves:1 --dry-run`: the move log, no lock
    "limits_what_if": lambda api, rec: api.limits_what_if("qobuz", 40),
    "check_music_folder": lambda api, rec: api.check_music_folder(str(api._paths.root.parent / "Elsewhere")),
    "add_playlist": lambda api, rec: _check_a_link(api),  # `playlist check`: a read job, the service read over the network: no lock
    "limits": lambda api, rec: api.limits("qobuz"),
    "playlists": lambda api, rec: api.playlists(),  # the playlists file and the stored read: no lock
    "downloads_view": lambda api, rec: api.downloads_view(),
    "find_logins": lambda api, rec: api.find_logins("soundcloud"),  # the browsers of `services()`: none
    "setup_check_tools": lambda api, rec: api.setup_check_tools(),
    "setup_status": lambda api, rec: api.setup_status(),
    "app_update": lambda api, rec: api.app_update(check=True),  # the cache file in the support folder's cache/ (T9's allowed write), no lock
    "show_in_finder": lambda api, rec: _opened(api.show_in_finder("t2", print_only=True)),  # the openers look at paths and open nothing with print_only: no lock
    "reveal": lambda api, rec: _opened(api.reveal("Library", print_only=True)),
    "open_report": lambda api, rec: _open_buy_list(api),
    "open_external": lambda api, rec: _opened(api.open_external("https://example.com", print_only=True)),
    "open_licenses": lambda api, rec: _opened(api.open_licenses(print_only=True)),
    "open_privacy_settings": lambda api, rec: _opened(api.open_privacy_settings(print_only=True)),
    "retry_music_folder": lambda api, rec: api.retry_music_folder(),  # a built read with no command of its own
    "aiff_plan": _aiff_plan,  # the dry run of both aiff commands (a read: the shared hold only while master.db is open)
}
BUILT = [e for e in catalog.ENTRIES if e.planned is None]


AUDIO_METHODS = {"rekordbox_preview", "convert", "rename", "make_aiff", "aiff_plan", "spectrum"}  # their drivers decode or write real audio


def skip_without_tools(entry):
    """These drivers run ffmpeg and ffprobe on a real file: without them the test skips, like the other audio tests."""
    if entry.method in AUDIO_METHODS and (shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None):
        pytest.skip("ffmpeg not installed")


@pytest.mark.parametrize("entry", BUILT, ids=lambda e: f"{e.method}:{' '.join(e.command)}")
def test_the_locks_a_built_entry_takes_are_its_locks_column(entry, box):
    skip_without_tools(entry)
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

def test_a_settings_job_takes_the_library_and_the_support_lock_and_the_brief_save_too(box):
    assert taken_by(box, lambda api, rec: wait_job(api, rec, api.setup_skip_qobuz())) == {"library", "support"}


LOCK_ORDER = ("support", "library", "rekordbox_r", "rekordbox_w")  # the stated order: a lock is never taken after a later one


def order_of(box, drive) -> list[str]:
    """The locks `drive` takes, in the order it takes them (the recorder notes each take as it happens)."""
    api, events, rec = box
    rec.words.clear()
    drive(api, events)
    return list(rec.words)


RANK = {"support": 0, "library": 1, "rekordbox_r": 2, "rekordbox_w": 2}  # the two rekordbox.lock takes are one rank


def disorder_of(events: list[tuple[str, str, int]]) -> str | None:
    """The first lock taken while a later one is held (in one thread), else None. The rule is about holds that are open
    together: a lock that was let go before the next is taken (a reader's preview, then the library) is no breach."""
    held: dict[int, list[str]] = {}
    for what, word, thread in events:
        mine = held.setdefault(thread, [])
        if what == "release":
            mine.remove(word)
            continue
        later = [h for h in mine if RANK[h] > RANK[word]]
        if later:
            return f"{word} is taken while {later[0]} is held: {[e[:2] for e in events]}"
        mine.append(word)
    return None


@pytest.mark.parametrize("entry", [pytest.param(e, id=f"{e.method}:{' '.join(e.command)}") for e in BUILT])
def test_a_built_entry_takes_its_locks_in_the_stated_order(entry, box):
    """Lock order is support, library, rekordbox.lock: a lock taken while another is held comes later in that order
    (a reader after a writer is allowed: both are `rekordbox.lock`). Only holds that are open together count."""
    skip_without_tools(entry)
    if entry.kind in ("W", "dropped"):
        return
    own = f"{entry.method}:{' '.join(entry.command)}"
    driver = DRIVERS.get(own) or DRIVERS.get(entry.method)
    api, events, rec = box
    rec.words.clear()
    rec.events.clear()
    driver(api, events)
    assert disorder_of(rec.events) is None, disorder_of(rec.events)


def test_the_order_check_fails_when_the_library_is_taken_while_the_reader_hold_is_open(box, tmp_path):
    """The check is not blind: a driver that takes `library` inside a `rekordbox_r` hold is a breach, and the same two
    takes one after the other (the hold let go first) are not."""
    api, events, rec = box
    support, music = api._support.support, api._paths.root / ".discjockey"
    rec.events.clear()
    with rb_lock.reader_lock(support):
        with library.run_lock(music / "scratch.lock"):
            pass
    assert "library is taken while rekordbox_r is held" in (disorder_of(rec.events) or "")
    rec.events.clear()
    with rb_lock.reader_lock(support):
        pass
    with library.run_lock(music / "scratch.lock"):
        pass
    assert disorder_of(rec.events) is None
    rec.events.clear()
    with library.run_lock(music / "scratch.lock"):  # the allowed way round: the reader inside the library lock
        with rb_lock.reader_lock(support):
            pass
    assert disorder_of(rec.events) is None


def _music_elsewhere(api, rec):
    other = api._paths.root.parent / "other music"
    assert api.set_music_folder(str(other))["ok"]


SETTINGS_WRITES = {  # every settings write of the hub that takes both the support lock and the library lock
    "set_auto_upgrade (settings set)": lambda api, rec: wait_job(api, rec, api.set_auto_upgrade(False)),
    "setup_skip_qobuz": lambda api, rec: wait_job(api, rec, api.setup_skip_qobuz()),
    "setup_skip_spotify": lambda api, rec: wait_job(api, rec, api.setup_skip_spotify()),
    "setup_forget_account": lambda api, rec: wait_job(api, rec, api.setup_forget_account("youtube")),
    "setup_skip_import (brief save, no job)": lambda api, rec: api.setup_skip_import(),
    "set_music_folder (setup music)": _music_elsewhere,
}


@pytest.mark.parametrize("name", sorted(SETTINGS_WRITES))
def test_a_settings_write_takes_the_support_lock_first_then_the_library_lock_briefly_inside_it(name, box):
    """Lock order is support, library, rekordbox.lock (design §6.1): a settings write takes the support lock around its
    read-change-write and the library lock inside it, in a job and outside one, on the command line's path and the
    window's."""
    words = order_of(box, SETTINGS_WRITES[name])
    assert words == ["support", "library"], words
    ranks = [LOCK_ORDER.index(w) for w in words]
    assert ranks == sorted(ranks)


def test_a_settings_job_holds_no_library_lock_while_it_waits_for_the_support_lock(box):
    """The order's other half: with the support lock held by another process the job answers busy (support_lock)
    without ever having taken the library lock."""
    from discjockey import library as lib
    api, events, rec = box
    rec.words.clear()
    old, lib.SUPPORT_WAIT_S = lib.SUPPORT_WAIT_S, 0.2
    try:
        with lib.support_lock(api._support.support):
            rec.words.clear()
            job = wait_job(api, events, api.set_auto_upgrade(False))
    finally:
        lib.SUPPORT_WAIT_S = old
    assert (job.ok, job.problem) == (False, "busy") and "library" not in rec.words


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
