"""`rekordbox.match.classify` (issue 39): each kind of finding, which kind wins, folded comparison, the counts."""
import os
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

from discjockey.names import fold
from discjockey.rekordbox import Entry, Unreadable, match

ROOT = Path("/m")
DRIVE = Path("/Volumes/Crate")


def track(id: str, path: str) -> Entry:
    return Entry(id=id, folder_path=path, file_name=Path(path).name, file_type=1, analysis_path=None, title=f"Title {id}",
                 artist=f"Artist {id}", album="", label="", isrc="", comment="", cloud=False, created_at=None,
                 artist_id=None, album_id=None, label_id=None, org_folder_path="", local_folder_path=None,
                 file_size=None, uuid=None)


def run(tracks, *, library=(), away=(), there=(), roots=(ROOT, DRIVE)):
    """`classify` with `library` = the paths of the songs' current files (keys `s0`, `s1`, ...), `there` = the paths that
    exist."""
    files = {fold(p): (f"s{i}", Path(p)) for i, p in enumerate(library)}
    present = {fold(p) for p in there}
    return match.classify(tracks, root=ROOT, roots=roots, library_files=files, away_roots=away,
                          exists=lambda p: fold(str(p)) in present)


def kinds(rows):
    return {r.entry.id if r.entry else r.key: r.kind for r in rows}


def test_each_kind():
    paths = {"a": "/m/Library/A/a.aiff", "b": "/m/Library/A/b.aiff", "c": "/m/Library/A/c.aiff",
             "d": "/m/Superseded/A/d.mp3", "e": "/Volumes/Crate/e.mp3", "f": "/Users/dj/Music/f.mp3",
             "g": "/m/Library/A/g.aiff"}
    rows = run([track(i, p) for i, p in paths.items()], library=[paths["a"], "/m/Library/A/lack.aiff"],
               away=[DRIVE], there=[paths["a"], paths["b"], paths["c"], paths["f"], paths["g"], "/m/Library/A/lack.aiff"])
    assert kinds(rows) == {"a": "matched", "b": "not_in_library", "c": "not_in_library", "d": "superseded",
                           "e": "away", "f": "outside", "g": "not_in_library", "s1": "not_in_rekordbox"}
    missing = run([track("m", "/m/Library/A/gone.aiff")], there=[])
    assert kinds(missing) == {"m": "missing"}


def test_the_first_kind_that_applies_wins():
    gone = "/m/Superseded/A/old.mp3"  # not there, but a replaced file: superseded, not missing
    assert kinds(run([track("1", gone)], there=[])) == {"1": "superseded"}
    drive = "/Volumes/Crate/x.mp3"  # a drive that is away: its files are not there, but that is not "missing"
    assert kinds(run([track("2", drive)], away=[DRIVE], there=[])) == {"2": "away"}
    assert kinds(run([track("3", drive)], there=[])) == {"3": "missing"}  # the drive is connected, the file is gone


def test_an_own_file_elsewhere_is_outside_but_a_missing_one_is_missing():
    elsewhere = "/Users/dj/Music/x.mp3"
    assert kinds(run([track("1", elsewhere)], there=[elsewhere])) == {"1": "outside"}
    assert kinds(run([track("1", elsewhere)], there=[])) == {"1": "missing"}


def test_paths_compare_folded():
    nfd = unicodedata.normalize("NFD", "/m/Library/A/Beyoncé.aiff")
    stored = "/M/LIBRARY/a/beyoncé.AIFF"  # another case and Unicode form of the same file
    rows = run([track("1", stored)], library=[nfd], there=[nfd])
    assert kinds(rows) == {"1": "matched"} and rows[0].key == "s0"
    assert [r.kind for r in run([track("2", "/M/superseded/x.mp3")], there=[])] == ["superseded"]


def test_a_library_file_two_tracks_hold_is_held_and_one_rekordbox_lacks_is_not():
    file = "/m/Library/A/a.aiff"
    rows = run([track("1", file), track("2", file)], library=[file, "/m/Library/B/b.aiff"],
               there=[file, "/m/Library/B/b.aiff"])
    assert kinds(rows) == {"1": "matched", "2": "matched", "s1": "not_in_rekordbox"}
    lacking = [r for r in rows if r.kind == "not_in_rekordbox"]
    assert lacking[0].entry is None and lacking[0].key == "s1" and lacking[0].folded == fold("/m/Library/B/b.aiff")


def test_a_library_file_that_is_not_there_is_not_something_rekordbox_lacks():
    gone, here = "/m/Library/A/gone.aiff", "/m/Library/A/here.aiff"
    rows = run([], library=[gone, here], there=[here])
    assert kinds(rows) == {"s1": "not_in_rekordbox"}


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens every folder")
def test_present_does_not_claim_a_file_missing_that_it_cannot_look_at(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    (folder / "a.aiff").write_bytes(b"x")
    folder.chmod(0)
    try:
        assert match.present(folder / "a.aiff") is True  # macOS refuses the folder: Path.exists() would raise
    finally:
        folder.chmod(0o755)
    assert match.present(folder / "a.aiff") is True
    assert match.present(folder / "b.aiff") is False


def test_rows_come_in_listed_order_then_by_folded_path_and_the_counts_add_up():
    paths = [f"/m/Library/A/{n}.aiff" for n in "cba"]
    tracks = [track("1", "/m/Superseded/z.mp3"), *[track(str(i + 2), p) for i, p in enumerate(paths)],
              track("9", "/m/Library/A/gone.aiff")]
    rows = run(tracks, library=[], there=paths)
    assert [r.kind for r in rows] == ["missing", "superseded", "not_in_library", "not_in_library", "not_in_library"]
    assert [r.folded for r in rows[2:]] == sorted(fold(p) for p in paths)
    assert Counter(r.kind for r in rows) == {"missing": 1, "superseded": 1, "not_in_library": 3}


def test_read_makes_an_unreadable_library_of_a_failed_read(monkeypatch, tmp_path):
    import sqlcipher3

    from discjockey.rekordbox import master

    class Library:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(master, "open_read", lambda place, running: Library())

    def fails(library):
        raise sqlcipher3.DatabaseError("database is locked")

    with pytest.raises(Unreadable) as busy:
        match.read(None, True, fails)
    with pytest.raises(Unreadable) as broken:
        match.read(None, False, fails)
    assert (busy.value.problem, broken.value.problem) == ("busy", "schema")
