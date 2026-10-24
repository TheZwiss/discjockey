"""library.scan_library and db.apply_scan end to end, on tmp_path libraries with real small AIFFs (plan library
stage 1, tasks 3.2 and 3.6)."""
import shutil
from datetime import date, datetime

import pytest

from audio_helpers import music, write_aiff
from discjockey import content_key, db, library
from discjockey.library import Paths, empty_state, load_state, save_state, scan_library
from discjockey.models import ScanResult, SeenFile


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    (p.library / "F").mkdir(parents=True)
    p.data.mkdir()
    return p


def song(paths, key="t1", rel="Library/F/A - X.aiff", seed=0, status="not_lossless"):
    """A song whose file Discjockey placed, and the records that know it."""
    write_aiff(paths.root / rel, music(1, seed))
    s = load_state(paths) if paths.db_file.exists() else empty_state()
    s["tracks"][key] = {"artist": "A", "title": key, "folder": "F", "path": rel, "status": status,
                        "source": "youtube_music", "source_id": "yt1", "source_format": "opus", "cutoff_hz": 16000,
                        "source_kbps": 128}
    save_state(paths, s)
    return rel


def scan(paths, **kw):
    messages = []
    summary = scan_library(paths, messages.append, analyze=kw.pop("analyze", lambda p: ("pcm_s16be", None)), **kw)
    return summary, [m.text for m in messages if m.level == "info"]


def counting_keys():
    calls = []

    def key_of(path):
        calls.append(path)
        return content_key.content_key(path)
    return key_of, calls


def test_a_file_moved_by_hand_keeps_its_song(paths):
    rel = song(paths)
    (paths.library / "Mine").mkdir()
    shutil.move(paths.root / rel, paths.library / "Mine" / "A - X.aiff")
    summary, messages = scan(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["placed_by"], e["status"], e["source"]) == (
        "Library/Mine/A - X.aiff", "user", "not_lossless", "youtube_music")
    assert summary.moved == 1 and messages == ["Checked your Library: 1 file you moved."]
    assert load_state(paths)["files"] == ["Library/Mine/A - X.aiff"]


def test_a_deleted_file_marks_its_song(paths):
    rel = song(paths)
    (paths.root / rel).unlink()
    summary, messages = scan(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["status"], e["file_gone"]) == (None, "missing", date.today().isoformat())
    assert summary.gone == 1 and messages == ["Checked your Library: 1 file gone."]


def test_a_copy_indexed_before_the_original_was_deleted_keeps_the_song(paths):
    rel = song(paths)
    shutil.copy(paths.root / rel, paths.library / "Copy.aiff")
    scan(paths)  # the window came to the front: the copy is indexed
    (paths.root / rel).unlink()
    summary, messages = scan(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["status"], e.get("file_gone"), e["placed_by"]) == (
        "Library/Copy.aiff", "not_lossless", None, "user")
    assert summary.moved == 1 and summary.gone == 0


def test_a_file_put_back_from_the_trash_after_a_scan_changes_nothing(paths):
    rel = song(paths)
    shutil.copy(paths.root / rel, paths.library / "Copy.aiff")
    scan(paths)
    trash = paths.root.parent / "Trash.aiff"
    shutil.move(paths.root / rel, trash)  # moved to the Trash: the song's file is the copy now
    scan(paths)
    shutil.move(trash, paths.root / rel)  # Put Back
    summary, _ = scan(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e.get("file_gone")) == ("Library/Copy.aiff", None)
    assert summary.gone == 0 and sorted(load_state(paths)["files"]) == ["Library/Copy.aiff", rel]


def test_a_file_replaced_outside_discjockey_is_judged_again(paths):
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))  # other audio under the same name
    judged = []

    def analyze(path):
        judged.append(path)
        return "pcm_s16be", None
    summary, messages = scan(paths, analyze=analyze)
    e = load_state(paths)["tracks"]["t1"]
    assert judged == [paths.root / rel]
    assert (e["path"], e["status"], e["source"], e["source_id"], e["source_format"], e["cutoff_hz"],
            e["source_kbps"]) == (rel, "lossless", "manual", None, "pcm_s16be", None, None)
    assert summary.replaced == 1 and messages == ["Checked your Library: 1 file changed."]


def test_a_replaced_file_the_tools_cant_read_keeps_its_quality(paths):
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))
    messages = []

    def analyze(path):
        raise RuntimeError("no audio stream")
    scan_library(paths, messages.append, analyze=analyze)
    assert load_state(paths)["tracks"]["t1"]["status"] == "not_lossless"
    assert any(m.level == "warning" and "couldn't check its sound" in m.text for m in messages)


def test_the_real_quality_check_judges_a_replaced_file(paths):
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))
    scan_library(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["source"], e["source_format"]) == ("manual", "pcm_s16be")
    assert e["status"] in ("lossless", "fake_lossless")


def test_nothing_changed_reads_no_file_and_says_nothing(paths):
    song(paths)
    song(paths, "t2", "Library/F/A - Y.aiff", seed=1)
    key_of, calls = counting_keys()
    summary, messages = scan(paths, key_of=key_of)
    assert calls == [] and messages == [] and summary == library.ScanSummary()


def test_new_files_are_indexed_and_counted(paths):
    song(paths)
    write_aiff(paths.library / "F" / "B - New.aiff", music(1, seed=3))
    write_aiff(paths.library / "F" / "C - New.aiff", music(1, seed=4))
    shutil.copy(paths.library / "F" / "B - New.aiff", paths.library / "F" / "B - Copy.aiff")
    summary, messages = scan(paths)
    assert (summary.new, summary.copies) == (3, 0)  # two new files with one key: neither is "the" original
    assert messages == ["Checked your Library: 3 new files."]
    snap = load_state(paths)
    assert snap["files"] == ["Library/F/A - X.aiff", "Library/F/B - Copy.aiff", "Library/F/B - New.aiff",
                             "Library/F/C - New.aiff"]
    assert list(snap["tracks"]) == ["t1"]  # nobody's files: indexed, linked to no song
    assert scan(paths)[1] == []  # and known from now on


def test_the_words_list_every_kind_of_change_in_order(paths):
    moved = song(paths)
    gone = song(paths, "t2", "Library/F/A - Y.aiff", seed=1)
    changed = song(paths, "t3", "Library/F/A - Z.aiff", seed=2)
    shutil.move(paths.root / moved, paths.library / "A - X.aiff")
    (paths.root / gone).unlink()
    write_aiff(paths.root / changed, music(1, seed=9))
    write_aiff(paths.library / "F" / "B - New.aiff", music(1, seed=5))
    assert scan(paths)[1] == ["Checked your Library: 1 file you moved, 1 new file, 1 file gone, 1 file changed."]


def test_files_outside_library_and_non_audio_are_never_indexed(paths):
    song(paths)
    open_db = paths.db_file.read_bytes()
    (paths.library / "F" / "library.db").write_bytes(open_db)  # a stray copy of the records
    (paths.library / "F" / "notes.txt").write_text("hi")
    for folder in (paths.superseded / "F", paths.upgrades_ready, paths.tmp / "t9"):
        folder.mkdir(parents=True, exist_ok=True)
        write_aiff(folder / "Other.aiff", music(1, seed=6))
    summary, messages = scan(paths)
    assert summary == library.ScanSummary() and messages == []
    assert load_state(paths)["files"] == ["Library/F/A - X.aiff"]


def test_the_scan_migrates_a_library_first(paths):
    write_aiff(paths.library / "F" / "A - X.aiff", music(1))
    library.write_json_atomic(paths.state_file, {
        "version": 1, "pending": [], "never": {}, "qobuz_usage": {"days": {}, "signals": []},
        "tracks": {"t1": {"artist": "A", "title": "X", "folder": "F", "path": "Library/F/A - X.aiff",
                          "status": "lossless"}}})
    key_of, calls = counting_keys()
    summary, messages = scan(paths, key_of=key_of)
    assert paths.db_file.exists() and calls == []  # the migration read the key; the scan didn't need to
    assert summary == library.ScanSummary()


# --- db.apply_scan rules the end-to-end cases don't reach ---

def rows(paths):
    with db.connect(paths.db_file) as conn:
        return conn.execute("SELECT id, song, path, online, placed_by, ambiguous FROM files ORDER BY id").fetchall()


def test_an_offline_folder_keeps_its_rows_and_its_songs_stay_satisfied(paths):
    song(paths)
    with db.connect(paths.db_file) as conn:
        (folder,) = conn.execute("SELECT id FROM watched_folders").fetchone()
        db.apply_scan(conn, ScanResult(offline=[folder]), datetime(2026, 10, 24))
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["online"], e["status"]) == ("Library/F/A - X.aiff", False, "not_lossless")
    assert load_state(paths)["files"] == []
    with db.connect(paths.db_file) as conn:
        db.apply_scan(conn, ScanResult(), datetime(2026, 10, 24))
    assert load_state(paths)["tracks"]["t1"]["online"] is True


def test_a_moved_file_takes_the_place_of_an_earlier_candidate(paths):
    song(paths)
    with db.connect(paths.db_file) as conn:
        (folder,) = conn.execute("SELECT id FROM watched_folders").fetchone()
        (linked,) = conn.execute("SELECT id FROM files").fetchone()
        seen = SeenFile(folder, "G/A - X.aiff", 10, 1, "1:10:abc")
        db.apply_scan(conn, ScanResult(ambiguous=[(linked, ["Library/G/A - X.aiff", "Library/H/A - X.aiff"])],
                                       new=[seen, SeenFile(folder, "H/A - X.aiff", 10, 1, "1:10:abc")]),
                      datetime(2026, 10, 24))
        assert load_state(paths)["ambiguous"] == {"t1": ["Library/G/A - X.aiff", "Library/H/A - X.aiff"]}
        db.apply_scan(conn, ScanResult(moved=[(linked, seen)]), datetime(2026, 10, 25))
    assert [(r[2], r[1] is not None, r[4], r[5]) for r in rows(paths)] == [
        ("G/A - X.aiff", True, "user", None), ("H/A - X.aiff", False, "import", None)]
    assert load_state(paths)["ambiguous"] == {}


def test_a_held_file_is_left_as_it_is_but_marked_held_until_it_is_seen(paths):
    song(paths)
    before = rows(paths)
    with db.connect(paths.db_file) as conn:
        (linked,) = conn.execute("SELECT id FROM files").fetchone()
        (seen_before,) = conn.execute("SELECT last_seen FROM files").fetchone()
        db.apply_scan(conn, ScanResult(held=[linked]), datetime(2030, 1, 1))
        (seen_after,) = conn.execute("SELECT last_seen FROM files").fetchone()
    assert rows(paths) == before and seen_after == seen_before
    state = load_state(paths)
    assert state["tracks"]["t1"]["held"] is True and state["files"] == []  # the planner leaves the song alone
    with db.connect(paths.db_file) as conn:
        db.apply_scan(conn, ScanResult(unchanged=1), datetime(2030, 1, 2))  # seen again
    state = load_state(paths)
    assert state["tracks"]["t1"]["held"] is False and state["files"] == ["Library/F/A - X.aiff"]


def test_a_file_moved_into_a_folder_the_scan_cant_list_is_held(paths):
    rel = song(paths)
    locked = paths.library / "Locked"
    locked.mkdir()
    shutil.move(paths.root / rel, locked / "A - X.aiff")
    locked.chmod(0)
    try:
        scan(paths)
    finally:
        locked.chmod(0o755)
    state = load_state(paths)
    assert state["tracks"]["t1"]["held"] is True and state["tracks"]["t1"]["path"] == rel
    assert state["tracks"]["t1"].get("file_gone") is None


def test_an_unchanged_scan_writes_only_its_folders_last_scan(paths):
    song(paths)
    song(paths, key="t2", rel="Library/F/B - Y.aiff", seed=1)
    with db.connect(paths.db_file) as conn:
        before = conn.execute("SELECT * FROM files ORDER BY id").fetchall()
        assert db.apply_scan(conn, ScanResult(unchanged=2), datetime(2030, 1, 1)) == 1
        assert conn.execute("SELECT * FROM files ORDER BY id").fetchall() == before
        assert conn.execute("SELECT last_scan FROM watched_folders").fetchall() == [("2030-01-01T00:00:00",)]


def test_a_copy_of_a_known_file_counts_as_a_new_file(paths):
    rel = song(paths)
    shutil.copy(paths.root / rel, paths.library / "Copy.aiff")
    summary, messages = scan(paths)
    assert (summary.new, summary.copies) == (0, 1) and messages == ["Checked your Library: 1 new file."]
    assert load_state(paths)["tracks"]["t1"]["path"] == rel  # the song keeps its own file


def test_a_replaced_file_whose_check_failed_is_judged_again_next_time(paths):
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))

    def broken(path):
        raise RuntimeError("no audio stream")
    summary, _ = scan(paths, analyze=broken)
    assert summary.replaced == 0  # not recorded: its new key waits for a check that works
    judged = []

    def analyze(path):
        judged.append(path)
        return "pcm_s16be", None
    summary, messages = scan(paths, analyze=analyze)
    assert judged == [paths.root / rel] and summary.replaced == 1
    assert load_state(paths)["tracks"]["t1"]["source"] == "manual"


def test_a_crash_while_judging_a_replaced_file_writes_nothing(paths):
    rel = song(paths)
    (paths.library / "F" / "B - New.aiff").parent.mkdir(exist_ok=True)
    write_aiff(paths.library / "F" / "B - New.aiff", music(1, seed=3))
    write_aiff(paths.root / rel, music(1, seed=7))

    def crash(path):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        scan(paths, analyze=crash)
    assert load_state(paths)["files"] == [rel]  # the scan's changes all wait for the next scan
    judged = []
    summary, _ = scan(paths, analyze=lambda p: judged.append(p) or ("pcm_s16be", None))
    assert judged == [paths.root / rel] and (summary.replaced, summary.new) == (1, 1)


def test_the_scan_waits_while_a_step_is_pending(paths):
    rel = song(paths)
    state = load_state(paths)
    state["pending"].append({"track_id": "t9", "renames": [[".discjockey/.tmp/t9/x.aiff", "Library/F/x.aiff"]],
                             "entry": None})
    save_state(paths, state)
    (paths.root / rel).unlink()
    key_of, calls = counting_keys()
    summary, messages = scan(paths, key_of=key_of)  # its files are between two places
    assert summary == library.ScanSummary() and messages == [] and calls == []
    assert load_state(paths)["tracks"]["t1"]["path"] == rel
