import os
import signal

import pytest

from discjockey import library
from discjockey.names import strip_id_suffix
from discjockey.library import (
    NameReserver, Paths, deferred_interrupt, delete_parked, empty_state, load_state, op_paths, recover_pending,
    run_op,
    safe_rename, save_state,
)


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    (p.library / "A").mkdir(parents=True)
    p.data.mkdir()
    return p


def touch(paths, rel, data=b"x"):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


def test_choose_free_name(paths):
    r = NameReserver(paths.root, empty_state())
    assert r.choose("Library/A", "Artist - Song", ".aiff", "abcdef123") == "Library/A/Artist - Song.aiff"


def test_choose_avoids_file_on_disk_with_other_case(paths):
    touch(paths, "Library/A/artist - song.aiff")
    r = NameReserver(paths.root, empty_state())
    assert r.choose("Library/A", "Artist - Song", ".aiff", "abcdef123") == "Library/A/Artist - Song [abcdef].aiff"


def test_an_own_songs_name_in_the_way_gets_a_tag_without_a_colon(paths):
    touch(paths, "Upgrades ready/Music/Artist - Song.aiff")
    r = NameReserver(paths.root, empty_state())
    chosen = r.choose("Upgrades ready/Music", "Artist - Song", ".aiff", "local:12")
    assert chosen == "Upgrades ready/Music/Artist - Song [local 12].aiff"  # Finder would show a colon as "/"
    assert strip_id_suffix("Artist - Song [local 12].aiff", "local:12") == "Artist - Song.aiff"


def test_choose_avoids_name_in_state(paths):
    s = empty_state()
    s["tracks"]["other"] = {"path": "Library/A/Artist - Song.aiff"}
    r = NameReserver(paths.root, s)
    assert r.choose("Library/A", "Artist - Song", ".aiff", "abcdef123").endswith("[abcdef].aiff")


def test_choose_avoids_name_chosen_earlier_in_run(paths):
    r = NameReserver(paths.root, empty_state())
    first = r.choose("Library/A", "Artist - Song", ".aiff", "t1aaaaaaa")
    second = r.choose("Library/A", "Artist - Song", ".aiff", "t2bbbbbbb")
    assert first == "Library/A/Artist - Song.aiff"
    assert second == "Library/A/Artist - Song [t2bbbb].aiff"


def test_release_frees_a_name_only_if_the_file_is_gone(paths):
    s = empty_state()
    s["tracks"]["t1"] = {"path": "Library/A/Artist - Song.aiff"}  # file no longer on disk
    s["tracks"]["t2"] = {"path": "Library/A/Other.aiff"}
    touch(paths, "Library/A/Other.aiff")
    r = NameReserver(paths.root, s)
    r.release("Library/A/Artist - Song.aiff")
    r.release("Library/A/Other.aiff")
    assert r.choose("Library/A", "Artist - Song", ".aiff", "t1aaaaaaa") == "Library/A/Artist - Song.aiff"
    assert r.choose("Library/A", "Other", ".aiff", "t2bbbbbbb") == "Library/A/Other [t2bbbb].aiff"


def test_choose_falls_back_to_full_id(paths):
    touch(paths, "Library/A/Artist - Song.aiff")
    touch(paths, "Library/A/Artist - Song [abcdef].aiff")
    r = NameReserver(paths.root, empty_state())
    assert r.choose("Library/A", "Artist - Song", ".aiff", "abcdef123") == "Library/A/Artist - Song [abcdef123].aiff"


def test_safe_rename_refuses_to_overwrite(paths):
    touch(paths, "Library/A/src.aiff", b"new")
    touch(paths, "Library/A/dst.aiff", b"old")
    with pytest.raises(FileExistsError):
        safe_rename(paths.root, "Library/A/src.aiff", "Library/A/dst.aiff")
    assert (paths.root / "Library/A/dst.aiff").read_bytes() == b"old"
    assert (paths.root / "Library/A/src.aiff").exists()


def test_safe_rename_creates_folders(paths):
    touch(paths, "Library/A/src.aiff")
    safe_rename(paths.root, "Library/A/src.aiff", "Superseded/A/src.aiff")
    assert (paths.root / "Superseded/A/src.aiff").exists()


def test_run_op_applies_entry_and_clears_pending(paths):
    touch(paths, "Library/A/x.aiff")
    s = empty_state()
    run_op(paths, s, "t1", [("Library/A/x.aiff", "Library/B/x.aiff")], {"path": "Library/B/x.aiff"})
    assert (paths.root / "Library/B/x.aiff").exists()
    assert s["tracks"]["t1"] == {"path": "Library/B/x.aiff"} and s["pending"] == []
    saved = load_state(paths)
    assert saved["tracks"]["t1"]["path"] == "Library/B/x.aiff" and saved["pending"] == []
    assert saved["files"] == ["Library/B/x.aiff"]


def crashing_rename(monkeypatch, after: int):
    """safe_rename that does `after` renames, then dies as a power cut would (nothing after it runs)."""
    real, done = library.safe_rename, []

    def rename(root, src, dst):
        if len(done) == after:
            raise SystemExit("power cut")
        done.append(src)
        real(root, src, dst)
    monkeypatch.setattr(library, "safe_rename", rename)


@pytest.mark.parametrize("after", [0, 1])
def test_a_crash_during_run_op_is_finished_by_the_next_start(paths, monkeypatch, after):
    touch(paths, ".discjockey/.tmp/t1/new.aiff", b"new")
    touch(paths, "Library/A/S.aiff", b"old")
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "S", "path": "Library/A/S.aiff", "status": "not_lossless"}
    save_state(paths, s)
    crashing_rename(monkeypatch, after)
    entry = {**s["tracks"]["t1"], "status": "lossless"}
    with pytest.raises(SystemExit):
        run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff"),
                                (".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")], entry)
    monkeypatch.undo()
    on_disk = load_state(paths)
    assert len(on_disk["pending"]) == (1 if after else 0)  # the step survives the crash once a file moved
    msgs = recover_pending(paths, on_disk)
    after_start = load_state(paths)
    assert after_start["pending"] == []
    if after:
        assert msgs[0][1] is True
        assert (paths.root / "Library/A/S.aiff").read_bytes() == b"new"
        assert after_start["tracks"]["t1"]["status"] == "lossless"
    else:
        assert after_start["tracks"]["t1"]["status"] == "not_lossless"  # nothing was moved: as before


def test_a_crash_after_the_renames_is_finished_by_the_next_start(paths, monkeypatch):
    touch(paths, ".discjockey/.tmp/t1/new.aiff", b"new")
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "S", "path": None, "status": "missing"}
    save_state(paths, s)
    real, writes = library._records, []

    def records(paths_):
        if writes:
            raise SystemExit("power cut")  # the write that applies the entry never happens
        writes.append(1)
        return real(paths_)
    monkeypatch.setattr(library, "_records", records)
    entry = {**s["tracks"]["t1"], "path": "Library/A/S.aiff", "status": "lossless"}
    with pytest.raises(SystemExit):
        run_op(paths, s, "t1", [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")], entry)
    monkeypatch.undo()
    on_disk = load_state(paths)
    assert on_disk["tracks"]["t1"]["path"] is None and len(on_disk["pending"]) == 1
    recover_pending(paths, on_disk)
    after_start = load_state(paths)
    assert after_start["tracks"]["t1"]["path"] == "Library/A/S.aiff" and after_start["pending"] == []
    assert after_start["files"] == ["Library/A/S.aiff"]


def test_run_op_reads_the_content_key_of_a_file_written_under_its_old_name(paths):
    touch(paths, "Library/A/S.aiff", b"old")
    touch(paths, ".discjockey/.tmp/t1/new.aiff", b"new audio")
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "S", "path": "Library/A/S.aiff", "status": "lossless"}
    save_state(paths, s)
    run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff"),
                            (".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")], None)  # no entry change
    from discjockey import db
    with db.connect(paths.db_file) as conn:
        (size,) = conn.execute("SELECT size FROM files").fetchone()
    assert size == len(b"new audio")  # a scan won't call it replaced outside Discjockey


def test_run_op_failing_first_rename_leaves_state_clean(paths):
    touch(paths, "Library/A/x.aiff")
    touch(paths, "Library/B/x.aiff")
    s = empty_state()
    with pytest.raises(FileExistsError):
        run_op(paths, s, "t1", [("Library/A/x.aiff", "Library/B/x.aiff")], {"path": "Library/B/x.aiff"})
    assert s["pending"] == [] and "t1" not in s["tracks"]


def pending_state(paths, renames):
    s = empty_state()
    s["pending"].append({"track_id": "t1", "renames": [list(r) for r in renames],
                         "entry": {"artist": "A", "title": "S", "path": renames[0][1]}})
    save_state(paths, s)
    return s


def test_recover_when_nothing_was_renamed(paths):
    touch(paths, ".discjockey/.tmp/t1/new.aiff")
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")])
    msgs = recover_pending(paths, s)
    assert (paths.root / "Library/A/S.aiff").exists()
    assert s["tracks"]["t1"]["path"] == "Library/A/S.aiff" and s["pending"] == []
    assert msgs[0][1] is True


def test_recover_when_first_of_two_renames_was_done(paths):
    touch(paths, "Library/A/S.aiff")  # new file already placed
    touch(paths, "Library/A/not_lossless/S.aiff")  # old file not yet superseded
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff"),
                              ("Library/A/not_lossless/S.aiff", "Superseded/A/S.aiff")])
    recover_pending(paths, s)
    assert (paths.root / "Superseded/A/S.aiff").exists()
    assert "t1" in s["tracks"]


def test_recover_when_all_renames_were_done(paths):
    touch(paths, "Library/A/S.aiff")
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")])
    recover_pending(paths, s)
    assert s["tracks"]["t1"]["path"] == "Library/A/S.aiff"


def test_recover_keeps_upgrade_when_old_file_vanished(paths):
    touch(paths, "Library/A/S.aiff")  # the new file was placed; the old file is gone since
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff"),
                              ("Library/A/not_lossless/S.aiff", "Superseded/A/S.aiff")])
    msgs = recover_pending(paths, s)
    assert s["tracks"]["t1"]["path"] == "Library/A/S.aiff"
    assert msgs[0][1] is False and s["pending"] == []


def test_recover_drops_operation_when_files_are_gone(paths):
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")])
    msgs = recover_pending(paths, s)
    assert s["pending"] == [] and "t1" not in s["tracks"]
    assert msgs[0][1] is False
    assert load_state(paths)["pending"] == []


def test_recover_drops_operation_when_both_sides_exist(paths):
    touch(paths, ".discjockey/.tmp/t1/new.aiff")
    touch(paths, "Library/A/S.aiff")
    s = pending_state(paths, [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")])
    msgs = recover_pending(paths, s)
    assert msgs[0][1] is False and "t1" not in s["tracks"]


def test_deferred_interrupt_delays_ctrl_c():
    reached = []
    with pytest.raises(KeyboardInterrupt):
        with deferred_interrupt():
            os.kill(os.getpid(), signal.SIGINT)
            reached.append("after signal")
    assert reached == ["after signal"]


def test_deferred_interrupt_restores_handler():
    before = signal.getsignal(signal.SIGINT)
    with deferred_interrupt():
        pass
    assert signal.getsignal(signal.SIGINT) is before


def test_deferred_interrupt_hands_ctrl_c_to_the_previous_handler():
    calls = []
    previous = signal.signal(signal.SIGINT, lambda signum, frame: calls.append(signum))
    try:
        with deferred_interrupt():
            os.kill(os.getpid(), signal.SIGINT)
        assert calls == [signal.SIGINT]  # e.g. the console's "stop safely" handler, not a KeyboardInterrupt
    finally:
        signal.signal(signal.SIGINT, previous)


SWAP_OP = {"kind": "swap", "track_id": "t1", "target": "Library/A/not_lossless/S.aiff",
           "staged": ".discjockey/.tmp/t1/swap.aiff", "backup": "Superseded/A/S (lossy).aiff",
           "parked": "Upgrades ready/A/S.aiff", "renames": [["Library/A/not_lossless/S.aiff", "Library/A/S.aiff"]],
           "old_sha256": "0", "new_sha256": "1", "entry": None}


def test_op_paths_names_every_file_of_a_swap():
    assert sorted(op_paths(SWAP_OP)) == sorted([
        "Library/A/not_lossless/S.aiff", "Library/A/S.aiff", "Library/A/not_lossless/S.aiff",
        ".discjockey/.tmp/t1/swap.aiff", "Superseded/A/S (lossy).aiff", "Upgrades ready/A/S.aiff"])
    assert op_paths({"track_id": "t1", "renames": [["a", "b"]], "entry": None}) == ["a", "b"]


def test_names_of_a_pending_swap_are_reserved(paths):
    s = empty_state()
    s["pending"].append(SWAP_OP)
    r = NameReserver(paths.root, s)
    assert r.choose("Superseded/A", "S (lossy)", ".aiff", "t1aaaaaaa") == "Superseded/A/S (lossy) [t1aaaa].aiff"
    assert r.choose("Library/A", "S", ".aiff", "t1aaaaaaa") == "Library/A/S [t1aaaa].aiff"


def test_parked_upgrade_names_are_reserved(paths):
    s = empty_state()
    s["tracks"]["t2"] = {"path": "Library/A/not_lossless/S.aiff", "upgrade": {"file": "Upgrades ready/A/S.aiff"}}
    s["tracks"]["t3"] = {"path": "Library/A/x.aiff"}  # written before the field existed
    r = NameReserver(paths.root, s)
    assert r.choose("Upgrades ready/A", "S", ".aiff", "t1aaaaaaa") == "Upgrades ready/A/S [t1aaaa].aiff"


def test_upgrades_ready_sits_next_to_the_library(paths):
    assert paths.upgrades_ready == paths.root / "Upgrades ready"


def test_delete_parked_only_deletes_in_upgrades_ready(paths):
    touch(paths, "Upgrades ready/A/S.aiff")
    keep = touch(paths, "Library/A/S.aiff")
    delete_parked(paths, "Upgrades ready/A/S.aiff")
    assert not (paths.root / "Upgrades ready/A/S.aiff").exists()
    delete_parked(paths, "Upgrades ready/A/S.aiff")  # already gone: fine
    for rel in ("Library/A/S.aiff", "Upgrades ready/../Library/A/S.aiff"):
        with pytest.raises(ValueError):
            delete_parked(paths, rel)
    assert keep.exists()


def test_superseded_names_never_run_out(tmp_path):
    from discjockey.library import NameReserver, empty_state
    for name in ("Artist - Song", "Artist - Song [t1aaaa]", "Artist - Song [t1aaaaaaa]", "Artist - Song (2)"):
        (tmp_path / "Superseded/A").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"Superseded/A/{name}.aiff").write_bytes(b"x")
    names = NameReserver(tmp_path, empty_state())
    assert names.choose("Superseded/A", "Artist - Song", ".aiff", "t1aaaaaaa") == "Superseded/A/Artist - Song (3).aiff"
    assert names.choose("Superseded/A", "Artist - Song", ".aiff", "t1aaaaaaa") == "Superseded/A/Artist - Song (4).aiff"
    with pytest.raises(FileExistsError):  # in Library/ a name stays the correct one or carries the ID
        for _ in range(4):
            names.choose("Library/A", "Artist - Song", ".aiff", "t1aaaaaaa")


def test_run_lock_waits_a_moment_for_a_probe(tmp_path):
    import fcntl
    import threading
    from discjockey.library import run_lock
    lock = tmp_path / "discjockey.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # e.g. the hub's console probe in another process
    threading.Timer(0.03, os.close, [fd]).start()
    with run_lock(lock):
        pass


def test_run_lock_still_refuses_a_real_run(tmp_path):
    from discjockey.library import LockHeld, run_lock
    lock = tmp_path / "discjockey.lock"
    with run_lock(lock):
        with pytest.raises(LockHeld):
            with run_lock(lock):
                pass


def test_the_hub_probe_never_makes_its_own_job_fail(tmp_path):
    import threading
    from discjockey.hub.jobs import lock_free
    from discjockey.library import run_lock
    lock = tmp_path / "discjockey.lock"
    done = threading.Event()

    def probe():
        while not done.is_set():
            lock_free(lock)

    t = threading.Thread(target=probe)
    t.start()
    try:
        for _ in range(300):
            with run_lock(lock):
                pass
    finally:
        done.set()
        t.join()


# --- a step with several entries (plan library stage 2, task 3.1) ---

def two_songs_in(paths, folder):
    s = empty_state()
    for key, title in (("t1", "S"), ("t2", "T")):
        touch(paths, f"Library/{folder}/A - {title}.aiff", title.encode())
        s["tracks"][key] = {"artist": "A", "title": title, "path": f"Library/{folder}/A - {title}.aiff",
                            "status": "lossless", "folder": folder}
    save_state(paths, s)
    return s


def moved_entries(s, old, new):
    return {k: {**e, "path": e["path"].replace(f"Library/{old}/", f"Library/{new}/")} for k, e in s["tracks"].items()}


def test_run_op_moves_a_folder_and_applies_every_entry(paths):
    s = two_songs_in(paths, "Old")
    run_op(paths, s, "", [("Library/Old", "Library/New")], None, entries=moved_entries(s, "Old", "New"),
           label="the folder rename Old → New")
    saved = load_state(paths)
    assert {e["path"] for e in saved["tracks"].values()} == {"Library/New/A - S.aiff", "Library/New/A - T.aiff"}
    assert saved["pending"] == [] and not (paths.library / "Old").exists()


def test_a_folder_step_crashed_after_the_rename_is_finished_with_its_entries(paths, monkeypatch):
    s = two_songs_in(paths, "Old")
    real, writes = library._records, []

    def records(paths_):
        if writes:
            raise SystemExit("power cut")  # the write that applies the entries never happens
        writes.append(1)
        return real(paths_)
    monkeypatch.setattr(library, "_records", records)
    with pytest.raises(SystemExit):
        run_op(paths, s, "", [("Library/Old", "Library/New")], None, entries=moved_entries(s, "Old", "New"),
               label="the folder rename Old → New")
    monkeypatch.undo()
    on_disk = load_state(paths)
    assert on_disk["pending"][0]["label"] == "the folder rename Old → New"
    msgs = recover_pending(paths, on_disk)
    assert msgs == [("Finished an interrupted step for the folder rename Old → New", True)]
    after_start = load_state(paths)
    assert after_start["pending"] == []
    assert after_start["tracks"]["t2"]["path"] == "Library/New/A - T.aiff"


def test_a_single_songs_step_stores_neither_entries_nor_label(paths, monkeypatch):
    from discjockey import db
    touch(paths, "Library/A/x.aiff")
    s = empty_state()
    seen = []
    real = db.journal_step
    monkeypatch.setattr(db, "journal_step", lambda conn, op, gen: (seen.append(dict(op)), real(conn, op, gen))[1])
    run_op(paths, s, "t1", [("Library/A/x.aiff", "Library/B/x.aiff")], {"path": "Library/B/x.aiff"})
    assert set(seen[0]) == {"kind", "track_id", "renames", "entry"} and seen[0]["kind"] == "step"


# --- what a step leaves its caller (issue 25: pinned before run_op moved off the entry view) ---

def one_song(paths, path="Library/A/S.aiff", status="not_lossless"):
    touch(paths, path, b"old")
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "S", "path": path, "status": status}
    s["tracks"]["t2"] = {"artist": "B", "title": "T", "path": None, "status": "missing"}
    save_state(paths, s)
    return s


def test_after_a_step_the_caller_goes_on_saving_its_state(paths):
    s = one_song(paths)
    run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff")],
           {**s["tracks"]["t1"], "path": None, "status": "missing"})
    assert s["generation"] == load_state(paths)["generation"]
    s["tracks"]["t2"] = {**s["tracks"]["t2"], "hidden": True}
    save_state(paths, s)  # not stale
    saved = load_state(paths)
    assert saved["tracks"]["t1"]["path"] is None and saved["tracks"]["t1"]["status"] == "missing"
    assert saved["tracks"]["t2"]["hidden"] is True and saved["pending"] == []


def test_a_step_on_a_stale_state_is_refused_before_any_file_moves(paths):
    s = one_song(paths)
    other = load_state(paths)
    other["tracks"]["t2"] = {**other["tracks"]["t2"], "hidden": True}
    save_state(paths, other)
    with pytest.raises(library.StateError, match="changed while"):
        run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff")],
               {**s["tracks"]["t1"], "path": None, "status": "missing"})
    assert (paths.root / "Library/A/S.aiff").exists() and not (paths.root / "Superseded/A/S.aiff").exists()
    saved = load_state(paths)
    assert saved["pending"] == [] and saved["tracks"]["t1"]["path"] == "Library/A/S.aiff"


def test_a_step_cut_off_mid_way_stays_journaled_while_its_caller_goes_on(paths, monkeypatch):
    """The sync goes on after one action failed (execute.Executor): its next saves keep the half-done step pending,
    and the next start finishes it."""
    s = one_song(paths)
    touch(paths, ".discjockey/.tmp/t1/new.aiff", b"new")
    real, done = library.safe_rename, []

    def rename(root, src, dst):
        if done:
            raise OSError("disk full")
        done.append(src)
        real(root, src, dst)
    monkeypatch.setattr(library, "safe_rename", rename)
    entry = {**s["tracks"]["t1"], "status": "lossless"}
    with pytest.raises(OSError):
        run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff"),
                                (".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")], entry)
    monkeypatch.undo()
    assert len(s["pending"]) == 1 and s["tracks"]["t1"]["status"] == "not_lossless"
    s["tracks"]["t2"] = {**s["tracks"]["t2"], "hidden": True}
    save_state(paths, s)  # the caller's next save
    on_disk = load_state(paths)
    assert len(on_disk["pending"]) == 1 and on_disk["tracks"]["t2"]["hidden"] is True
    msgs = recover_pending(paths, on_disk)
    assert msgs == [("Finished an interrupted step for A - S", True)]
    after = load_state(paths)
    assert after["pending"] == [] and after["tracks"]["t1"]["status"] == "lossless"
    assert (paths.root / "Library/A/S.aiff").read_bytes() == b"new"


def test_a_step_without_an_entry_changes_no_song(paths):
    s = one_song(paths, status="lossless")
    touch(paths, ".discjockey/.tmp/t2/bought.wav", b"bought")
    before = load_state(paths)["tracks"]
    run_op(paths, s, "t2", [(".discjockey/.tmp/t2/bought.wav", "Library/A/B - T.wav")], None)
    saved = load_state(paths)
    assert saved["tracks"] == before and saved["pending"] == []
    assert (paths.root / "Library/A/B - T.wav").read_bytes() == b"bought"


def test_a_step_onto_another_songs_file_is_refused_by_the_records(paths):
    s = one_song(paths, status="lossless")
    touch(paths, ".discjockey/.tmp/t2/new.aiff", b"new")
    with pytest.raises(library.StateError, match="same file"):
        run_op(paths, s, "t2", [(".discjockey/.tmp/t2/new.aiff", "Library/A/T.aiff")],
               {**s["tracks"]["t2"], "path": "Library/A/S.aiff", "status": "lossless"})
    saved = load_state(paths)
    assert saved["tracks"]["t1"]["path"] == "Library/A/S.aiff" and saved["tracks"]["t2"]["path"] is None


def test_a_step_writes_only_its_own_songs_and_the_callers_next_save_the_rest(paths):
    s = one_song(paths)
    s["tracks"]["t2"] = {**s["tracks"]["t2"], "hidden": True}  # not saved yet
    run_op(paths, s, "t1", [("Library/A/S.aiff", "Superseded/A/S.aiff")],
           {**s["tracks"]["t1"], "path": None, "status": "missing"})
    saved = load_state(paths)
    assert saved["tracks"]["t1"]["path"] is None and not saved["tracks"]["t2"].get("hidden")
    save_state(paths, s)
    assert load_state(paths)["tracks"]["t2"]["hidden"] is True
