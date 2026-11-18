"""library.scan_library and db.apply_scan end to end, on tmp_path libraries with real small AIFFs (plan library
stage 1, tasks 3.2 and 3.6)."""
import os
import shutil
from datetime import datetime

import pytest

from audio_helpers import music, write_aiff
from discjockey import content_key, db, library, quality
from discjockey.library import Paths, empty_state, load_state, save_state, scan_library
from discjockey.models import OwnFacts, ScanResult, SeenFile


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


def test_a_deleted_file_makes_its_song_wait(paths):
    rel = song(paths)
    (paths.root / rel).unlink()
    summary, messages = scan(paths)
    state = load_state(paths)
    e = state["tracks"]["t1"]
    assert (e["path"], e["status"], e.get("file_gone")) == (rel, "not_lossless", None)  # kept, nothing downloaded
    assert e["missing_since"] is not None and state["files"] == []
    assert summary.missing == 1 and summary.gone == 0
    assert messages == ["Checked your Library: 1 file missing. Missing files wait in To-do."]
    summary, messages = scan(paths)  # the next scans find it as missing again and say nothing more
    assert summary == library.ScanSummary() and messages == []


def test_a_copy_indexed_before_the_original_was_deleted_keeps_the_song(paths):
    rel = song(paths)
    shutil.copy(paths.root / rel, paths.library / "Copy.aiff")
    scan(paths)  # the window came to the front: the copy is indexed
    (paths.root / rel).unlink()
    summary, messages = scan(paths)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["status"], e.get("file_gone"), e["placed_by"]) == (
        "Library/Copy.aiff", "not_lossless", None, "user")
    assert summary.moved == 1 and summary.gone == 0 and summary.missing == 0


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
    assert summary.missing == 0 and summary.gone == 0 and sorted(load_state(paths)["files"]) == ["Library/Copy.aiff", rel]


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
    back = song(paths, "t4", "Library/F/A - W.aiff", seed=3)
    lost = song(paths, "t2", "Library/F/A - Y.aiff", seed=1)
    changed = song(paths, "t3", "Library/F/A - Z.aiff", seed=2)
    (paths.root / back).rename(paths.root.parent / "W.aiff")
    scan(paths)  # t4 waits as missing
    shutil.move(paths.root / moved, paths.library / "A - X.aiff")
    shutil.move(paths.root.parent / "W.aiff", paths.library / "A - W.aiff")  # put back under the same name elsewhere
    (paths.root / lost).unlink()
    write_aiff(paths.root / changed, music(1, seed=9))
    write_aiff(paths.library / "F" / "B - New.aiff", music(1, seed=5))
    assert scan(paths)[1] == ["Checked your Library: 1 file you moved, 1 new file, 1 missing file back, "
                              "1 file missing, 1 file changed. Missing files wait in To-do."]


def test_the_words_of_a_scan_with_only_files_back_have_no_second_sentence(paths):
    rel = song(paths)
    (paths.root / rel).rename(paths.root.parent / "away.aiff")
    scan(paths)
    (paths.root.parent / "away.aiff").rename(paths.root / rel)
    summary, messages = scan(paths)
    assert (summary.back, summary.moved, summary.missing) == (1, 0, 0)
    assert messages == ["Checked your Library: 1 missing file back."]


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


def test_an_unjudged_file_is_left_as_it_is_but_marked_held_until_it_is_seen(paths):
    song(paths)
    before = rows(paths)
    with db.connect(paths.db_file) as conn:
        (linked,) = conn.execute("SELECT id FROM files").fetchone()
        (seen_before,) = conn.execute("SELECT last_seen FROM files").fetchone()
        db.apply_scan(conn, ScanResult(unjudged=[linked]), datetime(2030, 1, 1))
        (seen_after,) = conn.execute("SELECT last_seen FROM files").fetchone()
    assert rows(paths) == before and seen_after == seen_before
    state = load_state(paths)
    assert state["tracks"]["t1"]["held"] is True and state["files"] == []  # the planner leaves the song alone
    with db.connect(paths.db_file) as conn:
        db.apply_scan(conn, ScanResult(unchanged=1), datetime(2030, 1, 2))  # seen again
    state = load_state(paths)
    assert state["tracks"]["t1"]["held"] is False and state["files"] == ["Library/F/A - X.aiff"]


def test_a_file_moved_into_a_folder_the_scan_cant_list_waits_and_links_back_once_it_is_listable(paths):
    rel = song(paths)
    locked = paths.library / "Locked"
    locked.mkdir()
    shutil.move(paths.root / rel, locked / "A - X.aiff")
    locked.chmod(0)
    try:
        summary, _ = scan(paths)
    finally:
        locked.chmod(0o755)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["held"], e.get("file_gone")) == (rel, False, None)
    assert e["missing_since"] is not None and summary.missing == 1
    summary, messages = scan(paths)  # listable now: the file is found by its key and the song links back
    e = load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["missing_since"]) == ("Library/Locked/A - X.aiff", None)
    assert (summary.back, summary.moved) == (1, 0) and messages == ["Checked your Library: 1 missing file back."]


def test_a_song_whose_audio_failed_the_sound_check_is_held_not_missing(paths):
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))

    def broken(path):
        raise RuntimeError("no audio stream")
    scan(paths, analyze=broken)
    e = load_state(paths)["tracks"]["t1"]
    assert (e["held"], e["missing_since"], e["path"]) == (True, None, rel)  # it is there; it just can't be judged


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


def test_a_replaced_file_whose_check_failed_is_not_judged_again_until_its_bytes_or_the_tools_change(paths,
                                                                                                    monkeypatch):
    monkeypatch.setattr(quality, "tools_stamp", lambda: "tools-1")
    rel = song(paths)
    write_aiff(paths.root / rel, music(1, seed=7))
    calls = []

    def broken(path):
        calls.append(path)
        raise RuntimeError("no audio stream")
    summary, _ = scan(paths, analyze=broken)
    assert summary.replaced == 0 and len(calls) == 1  # not recorded: its new key waits for a check that works
    for _ in range(2):  # the same bytes, the same tools: not tried again, and no second warning
        messages = []
        scan_library(paths, messages.append, analyze=broken)
        assert [m.level for m in messages] == []
    assert len(calls) == 1
    monkeypatch.setattr(quality, "tools_stamp", lambda: "tools-2")  # ffmpeg was installed or updated
    scan(paths, analyze=broken)
    assert len(calls) == 2
    write_aiff(paths.root / rel, music(1, seed=8))  # the bytes changed
    scan(paths, analyze=broken)
    assert len(calls) == 3
    judged = []

    def analyze(path):
        judged.append(path)
        return "pcm_s16be", None
    summary, messages = scan(paths, analyze=analyze)  # same bytes and tools as the last failure: still waits ...
    assert judged == [] and summary.replaced == 0
    monkeypatch.setattr(quality, "tools_stamp", lambda: "tools-3")  # ... until something changes
    summary, messages = scan(paths, analyze=analyze)
    assert judged == [paths.root / rel] and summary.replaced == 1
    assert load_state(paths)["tracks"]["t1"]["source"] == "manual"
    with db.connect(paths.db_file) as conn:
        assert db.judge_failures(conn) == {}  # a judgment that works clears the note


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


# --- issue 43: a file a scan doesn't see waits as missing; it links back when a file with its key shows up ---

UPGRADE = {"file": "Upgrades ready/Own - Song.aiff", "source": "qobuz", "status": "lossless", "kbps": None,
           "cutoff_hz": 22000, "found": "2026-11-01"}


@pytest.fixture
def mine(tmp_path):
    """A music folder with an import folder `crate` and a second one `more` next to it, and an own song (a file the
    import read) in `crate` with a better version parked for it."""
    p = Paths(tmp_path / "music", support=tmp_path / ".support")
    (p.library / "F").mkdir(parents=True)
    p.data.mkdir()
    for name in ("crate", "more", "away"):
        (tmp_path / name).mkdir()
    write_aiff(tmp_path / "crate" / "Own - Song.aiff", music(1, seed=11))
    library.open_records(p)
    with db.connect(p.db_file) as conn:
        db.add_watched_folder(conn, tmp_path / "crate", datetime(2026, 11, 1))
        db.add_watched_folder(conn, tmp_path / "more", datetime(2026, 11, 1))
    scan(p)
    with db.connect(p.db_file) as conn:
        (file_id,) = conn.execute("SELECT id FROM files WHERE path = 'Own - Song.aiff'").fetchone()
        key = db.add_own_song(conn, file_id, OwnFacts("Own", "Song", None, None, 200000, "aiff", "lossless"))
    state = load_state(p)
    state["tracks"][key]["upgrade"] = dict(UPGRADE)
    save_state(p, state)
    return p


def things(paths):
    """The import folders of `mine`, the folder outside them, the own song's key and its file row's id."""
    top = paths.root.parent
    with db.connect(paths.db_file) as conn:
        (file_id,) = conn.execute("SELECT f.id FROM files f JOIN songs s ON s.id = f.song WHERE s.key LIKE 'local:%'"
                                  ).fetchone()
    return {"crate": top / "crate", "more": top / "more", "away": top / "away", "key": "local:1", "file_id": file_id}


def file_row(paths, file_id):
    with db.connect(paths.db_file) as conn:
        return conn.execute("SELECT id, song, folder, path, placed_by, missing_since, ambiguous FROM files "
                            "WHERE id = ?", (file_id,)).fetchone()


def unlinked(paths):
    with db.connect(paths.db_file) as conn:
        return conn.execute("SELECT path FROM files WHERE song IS NULL").fetchall(), db.import_waiting(conn)


def test_an_own_song_whose_file_leaves_every_watched_folder_waits_and_links_back_at_its_path(mine):
    x = things(mine)
    key, file_id = x["key"], x["file_id"]
    song_before = load_state(mine)["tracks"][key]
    with db.connect(mine.db_file) as conn:  # an answer naming the own song
        db.set_decision(conn, "same_song", "sp9", key, "not_same", datetime(2026, 11, 2))
        (song_id,) = conn.execute("SELECT id FROM songs WHERE key = ?", (key,)).fetchone()
    shutil.move(x["crate"] / "Own - Song.aiff", x["away"] / "Own - Song.aiff")
    summary, messages = scan(mine)
    assert (summary.missing, summary.gone, summary.back) == (1, 0, 0)
    assert messages == ["Checked your Library: 1 file missing. Missing files wait in To-do."]
    state = load_state(mine)
    e = state["tracks"][key]
    assert e["upgrade"] == UPGRADE and e["file_id"] == file_id and e["missing_since"] is not None
    assert e["path"].endswith("/crate/Own - Song.aiff") and e.get("file_gone") is None
    assert all(not f.endswith("Own - Song.aiff") for f in state["files"])  # not a file that is there
    since = file_row(mine, file_id)[5]
    shutil.move(x["away"] / "Own - Song.aiff", x["crate"] / "Own - Song.aiff")
    summary, messages = scan(mine)
    assert (summary.back, summary.missing, summary.moved, summary.new) == (1, 0, 0, 0)
    assert messages == ["Checked your Library: 1 missing file back."]
    state = load_state(mine)
    e = state["tracks"][key]
    assert e["upgrade"] == UPGRADE and e["file_id"] == file_id and e["missing_since"] is None
    assert {k: e[k] for k in ("artist", "title", "path", "placed_by")} == {
        k: song_before[k] for k in ("artist", "title", "path", "placed_by")}
    row = file_row(mine, file_id)
    assert (row[0], row[3], row[4], row[5]) == (file_id, "Own - Song.aiff", "import", None) and since is not None
    assert unlinked(mine) == ([], [])  # no unlinked import row, nothing waiting to import
    assert any(f.endswith("Own - Song.aiff") for f in state["files"])
    assert sorted(state["tracks"]) == [key]  # still the same one song
    with db.connect(mine.db_file) as conn:
        assert conn.execute("SELECT id FROM songs WHERE key = ?", (key,)).fetchall() == [(song_id,)]
        assert conn.execute("SELECT count(*) FROM songs").fetchone() == (1,)
        assert db.decisions(conn)["same_song"] == [["sp9", key, "not_same"]]  # the answer was there all along


def test_the_file_put_back_under_another_name_in_another_watched_folder_links_to_the_same_song(mine):
    x = things(mine)
    key, file_id = x["key"], x["file_id"]
    shutil.move(x["crate"] / "Own - Song.aiff", x["away"] / "Own - Song.aiff")
    scan(mine)
    shutil.move(x["away"] / "Own - Song.aiff", x["more"] / "Renamed.aiff")
    summary, messages = scan(mine)
    assert (summary.back, summary.moved, summary.missing) == (1, 0, 0)
    assert messages == ["Checked your Library: 1 missing file back."]
    e = load_state(mine)["tracks"][key]
    assert e["file_id"] == file_id and e["upgrade"] == UPGRADE and e["missing_since"] is None
    assert e["path"].endswith("/more/Renamed.aiff") and e["placed_by"] == "user"
    assert unlinked(mine) == ([], [])


def test_a_song_missing_for_three_scans_keeps_the_first_scans_date_and_is_counted_once(mine, monkeypatch):
    x = things(mine)

    class Clock(datetime):
        now_is = datetime(2026, 11, 10, 9, 0, 0)

        @classmethod
        def now(cls, tz=None):
            return cls.now_is
    monkeypatch.setattr(library, "datetime", Clock)
    shutil.move(x["crate"] / "Own - Song.aiff", x["away"] / "Own - Song.aiff")
    summaries = []
    for day in (10, 11, 12):
        Clock.now_is = datetime(2026, 11, day, 9, 0, 0)
        summaries.append(scan(mine))
    assert [s.missing for s, _ in summaries] == [1, 0, 0]
    assert [m for _, m in summaries[1:]] == [[], []]  # only the first scan says it
    assert file_row(mine, x["file_id"])[5] == "2026-11-10T09:00:00"
    shutil.move(x["away"] / "Own - Song.aiff", x["crate"] / "Own - Song.aiff")
    Clock.now_is = datetime(2026, 11, 13, 9, 0, 0)
    assert scan(mine)[0].back == 1
    assert file_row(mine, x["file_id"])[5] is None


def test_two_copies_make_the_missing_file_ambiguous_and_one_deleted_links_it_back(mine):
    x = things(mine)
    key, file_id = x["key"], x["file_id"]
    shutil.move(x["crate"] / "Own - Song.aiff", x["away"] / "Own - Song.aiff")
    scan(mine)
    since = file_row(mine, file_id)[5]
    shutil.copy(x["away"] / "Own - Song.aiff", x["crate"] / "Copy 1.aiff")
    shutil.copy(x["away"] / "Own - Song.aiff", x["more"] / "Copy 2.aiff")
    summary, messages = scan(mine)
    assert (summary.missing, summary.moved, summary.back) == (0, 0, 0)  # an ambiguous row isn't counted
    row = file_row(mine, file_id)
    assert row[5] == since and row[6] is not None  # still missing, its first date kept
    assert key in load_state(mine)["ambiguous"]
    (x["more"] / "Copy 2.aiff").unlink()
    summary, messages = scan(mine)
    assert (summary.back, summary.moved) == (1, 0) and messages == ["Checked your Library: 1 missing file back."]
    row = file_row(mine, file_id)
    assert row[5] is None and row[6] is None and row[3] == "Copy 1.aiff"
    assert load_state(mine)["tracks"][key]["upgrade"] == UPGRADE


def test_an_unlinked_row_whose_file_goes_is_deleted_with_the_keep_both_answer_naming_it(mine):
    x = things(mine)
    shutil.copy(x["crate"] / "Own - Song.aiff", x["more"] / "Second.aiff")
    scan(mine)
    with db.connect(mine.db_file) as conn:
        (group,) = db.duplicate_groups(conn)
        db.set_decision(conn, "keep_both", group.id, "", "keep", datetime(2026, 11, 2))
    (x["more"] / "Second.aiff").unlink()
    summary, messages = scan(mine)
    assert (summary.gone, summary.missing) == (1, 0) and messages == []  # an index row of nobody's file: not worded
    with db.connect(mine.db_file) as conn:
        assert [r[0] for r in conn.execute("SELECT path FROM files ORDER BY id")] == ["Own - Song.aiff"]
        assert db.decisions(conn)["keep_both"] == []
    assert load_state(mine)["tracks"][x["key"]]["upgrade"] == UPGRADE  # the song and what it has are untouched


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any folder")
def test_rows_under_an_unlistable_subfolder_stay_as_they_were(mine):
    x = things(mine)
    (x["crate"] / "Locked").mkdir()
    shutil.move(x["crate"] / "Own - Song.aiff", x["crate"] / "Locked" / "Own - Song.aiff")
    scan(mine)  # found by its key under Locked/
    file_id = x["file_id"]
    assert file_row(mine, file_id)[3] == "Locked/Own - Song.aiff"
    (x["crate"] / "Locked").chmod(0)
    try:
        summary, _ = scan(mine)  # present stays present
        assert summary == library.ScanSummary() and file_row(mine, file_id)[5] is None
        with db.connect(mine.db_file) as conn:  # a missing one stays missing
            conn.execute("UPDATE files SET missing_since = '2026-11-01T10:00:00' WHERE id = ?", (file_id,))
        summary, _ = scan(mine)
        assert summary == library.ScanSummary() and file_row(mine, file_id)[5] == "2026-11-01T10:00:00"
    finally:
        (x["crate"] / "Locked").chmod(0o755)
    summary, _ = scan(mine)  # listable again, and the file is there at its own path
    assert summary.back == 1 and file_row(mine, file_id)[5] is None


def test_a_file_that_comes_back_cancels_a_download_again_the_sync_hasnt_done(mine):
    x = things(mine)
    shutil.move(x["crate"] / "Own - Song.aiff", x["away"] / "Own - Song.aiff")
    scan(mine)
    with db.connect(mine.db_file) as conn:  # what the user's Download again sets
        conn.execute("UPDATE songs SET file_gone = '2026-11-12' WHERE key = ?", (x["key"],))
    assert load_state(mine)["tracks"][x["key"]]["file_gone"] == "2026-11-12"
    shutil.move(x["away"] / "Own - Song.aiff", x["crate"] / "Own - Song.aiff")
    scan(mine)
    assert load_state(mine)["tracks"][x["key"]].get("file_gone") is None
