"""The scanner: every case of spec library-and-sources §6.3 and §6.4 against temp folders and a fake content key."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from discjockey.models import KnownFile, SeenFile, WatchedFolder
from discjockey.scanner import away_reason, is_offline, scan


class Keys:
    """A content key that is the file's text; counts its calls and can act on a call."""

    def __init__(self, on_call=None):
        self.calls: list[Path] = []
        self.on_call = on_call

    def __call__(self, path: Path) -> str:
        self.calls.append(path)
        if self.on_call:
            self.on_call(path)
        return "k:" + path.read_text()


def put(folder: Path, rel: str, text: str, mtime_ns: int | None = None) -> Path:
    p = folder / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mtime_ns is not None:
        os.utime(p, ns=(mtime_ns, mtime_ns))
    return p


def known(fid: int, wf: WatchedFolder, rel: str, *, linked: bool = True, ambiguous: bool = False,
          key: str | None = "") -> KnownFile:
    """The row of the file at `rel` as it is on disk now (key "" = its text's key)."""
    p = wf.path / rel
    st = p.stat()
    if key == "":
        key = "k:" + p.read_text()
    return KnownFile(fid, wf.id, rel, st.st_size, st.st_mtime_ns, key, linked, ambiguous)


def snap(folder: int, rel: str) -> str:
    return f"{folder}/{rel}"


def run(folders, rows, keys=None, exclude=(), mounted=lambda p: True):
    return scan(list(folders), list(rows), exclude=list(exclude), snapshot_path=snap, key_of=keys or Keys(),
                mounted=mounted)


def seen(wf: WatchedFolder, rel: str) -> SeenFile:
    st = (wf.path / rel).stat()
    return SeenFile(wf.id, rel, st.st_size, st.st_mtime_ns, "k:" + (wf.path / rel).read_text())


@pytest.fixture
def lib(tmp_path) -> WatchedFolder:
    (tmp_path / "Library").mkdir()
    return WatchedFolder(1, tmp_path / "Library", "library")


def test_unchanged_reads_nothing(lib):
    put(lib.path, "House/A - One.aiff", "one")
    put(lib.path, "B - Two.flac", "two")
    keys = Keys()
    r = run([lib], [known(1, lib, "House/A - One.aiff"), known(2, lib, "B - Two.flac")], keys)
    assert keys.calls == []
    assert r.unchanged == 2
    assert r.retagged == r.replaced == r.moved == r.ambiguous == r.new == r.copies == r.gone == r.offline == []


def test_same_audio_new_mtime_is_retagged(lib):
    put(lib.path, "A - One.aiff", "one", mtime_ns=1_000_000_000)
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "A - One.aiff", "one", mtime_ns=2_000_000_000)
    r = run([lib], [row])
    assert r.retagged == [(1, seen(lib, "A - One.aiff"))]
    assert r.unchanged == 0 and r.replaced == [] and r.new == []


def test_other_audio_at_the_same_path_is_replaced(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "A - One.aiff", "louder one", mtime_ns=row.mtime_ns + 5)
    r = run([lib], [row])
    assert r.replaced == [(1, seen(lib, "A - One.aiff"))]
    assert r.retagged == [] and r.new == [] and r.copies == []


def test_moved_file_is_found_by_its_key(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    (lib.path / "Sets").mkdir()
    (lib.path / "A - One.aiff").rename(lib.path / "Sets" / "Renamed.aiff")
    r = run([lib], [row])
    assert r.moved == [(1, seen(lib, "Sets/Renamed.aiff"))]
    assert r.new == [] and r.copies == [] and r.gone == []


def test_moved_to_two_places_is_ambiguous_and_both_are_new(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "X/A - One.aiff", "one")
    put(lib.path, "Y/A - One.aiff", "one")
    (lib.path / "A - One.aiff").unlink()
    r = run([lib], [row])
    assert r.ambiguous == [(1, ["1/X/A - One.aiff", "1/Y/A - One.aiff"])]
    assert sorted(f.rel for f in r.new) == ["X/A - One.aiff", "Y/A - One.aiff"]
    assert r.moved == [] and r.gone == [] and r.copies == []


def test_an_ambiguous_row_is_decided_again_against_its_indexed_candidates(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff", ambiguous=True)
    put(lib.path, "X/A - One.aiff", "one")
    put(lib.path, "Y/A - One.aiff", "one")
    (lib.path / "A - One.aiff").unlink()
    candidates = [known(2, lib, "X/A - One.aiff", linked=False), known(3, lib, "Y/A - One.aiff", linked=False)]
    r = run([lib], [row, *candidates])
    assert r.ambiguous == [(1, ["1/X/A - One.aiff", "1/Y/A - One.aiff"])]
    assert r.unchanged == 2 and r.new == [] and r.gone == []
    (lib.path / "Y/A - One.aiff").unlink()  # the user removed the other one
    r = run([lib], [row, candidates[0], candidates[1]])
    assert r.moved == [(1, seen(lib, "X/A - One.aiff"))]
    assert r.gone == [3] and r.ambiguous == []


def test_an_ambiguous_row_found_back_at_its_path_is_retagged(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff", ambiguous=True)
    r = run([lib], [row])
    assert r.retagged == [(1, seen(lib, "A - One.aiff"))] and r.unchanged == 0


def test_gone_when_nothing_has_the_key(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    (lib.path / "A - One.aiff").unlink()
    put(lib.path, "B - Two.aiff", "two")
    r = run([lib], [row])
    assert r.gone == [1]
    assert r.new == [seen(lib, "B - Two.aiff")]


def test_copy_of_a_file_that_is_still_there(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "Backup/A - One.aiff", "one")
    r = run([lib], [row])
    assert r.copies == [seen(lib, "Backup/A - One.aiff")]
    assert r.new == [] and r.moved == [] and r.unchanged == 1


def test_a_gone_path_takes_a_new_file_with_its_key_even_when_the_key_is_elsewhere_too(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "B/A - One.aiff", "one")
    (lib.path / "A - One.aiff").rename(lib.path / "C.aiff")
    r = run([lib], [row, known(2, lib, "B/A - One.aiff")])
    assert r.moved == [(1, seen(lib, "C.aiff"))]  # moves are decided before copies (§6.3 order)
    assert r.copies == [] and r.new == [] and r.gone == []


def test_two_rows_one_new_place_the_linked_row_moves(lib):
    put(lib.path, "A.aiff", "one")
    put(lib.path, "B.aiff", "one")
    rows = [known(1, lib, "A.aiff", linked=False), known(2, lib, "B.aiff")]
    (lib.path / "A.aiff").unlink()
    (lib.path / "B.aiff").rename(lib.path / "C.aiff")
    r = run([lib], rows)
    assert r.moved == [(2, seen(lib, "C.aiff"))]
    assert r.gone == [1] and r.new == [] and r.copies == []


def test_new_files(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "Sub/B - Two.mp3", "two")
    r = run([lib], [])
    assert r.new == [seen(lib, "A - One.aiff"), seen(lib, "Sub/B - Two.mp3")]


def test_moves_across_watched_folders(lib, tmp_path):
    imp = WatchedFolder(2, tmp_path / "Import", "import")
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    imp.path.mkdir()
    (lib.path / "A - One.aiff").rename(imp.path / "A - One.aiff")
    r = run([lib, imp], [row])
    assert r.moved == [(1, seen(imp, "A - One.aiff"))]


def test_migrated_row_without_key_is_found_by_name(lib):
    row = KnownFile(1, lib.id, "House/A - One.aiff", None, None, None, True, False)
    put(lib.path, "Old/a - one.aiff", "one")
    put(lib.path, "Other.aiff", "two")
    r = run([lib], [row])
    assert r.moved == [(1, seen(lib, "Old/a - one.aiff"))]
    assert r.new == [seen(lib, "Other.aiff")]


def test_migrated_row_without_key_two_names_is_ambiguous_none_is_gone(lib):
    rows = [KnownFile(1, lib.id, "A - One.aiff", None, None, None, True, False),
            KnownFile(2, lib.id, "B - Two.aiff", None, None, None, True, False)]
    put(lib.path, "X/A - One.aiff", "one")
    put(lib.path, "Y/A - One.aiff", "one, another take")
    r = run([lib], rows)
    assert r.ambiguous == [(1, ["1/X/A - One.aiff", "1/Y/A - One.aiff"])]
    assert r.gone == [2]


def test_migrated_row_without_key_found_at_its_own_path_is_retagged(lib):
    put(lib.path, "A - One.aiff", "one")
    r = run([lib], [KnownFile(1, lib.id, "A - One.aiff", None, None, None, True, False)])
    assert r.retagged == [(1, seen(lib, "A - One.aiff"))]


def test_a_name_match_never_takes_a_file_a_key_already_took(lib):
    put(lib.path, "A - One.aiff", "one")
    keyed = known(1, lib, "A - One.aiff")
    (lib.path / "A - One.aiff").rename(lib.path / "Elsewhere.aiff")
    unkeyed = KnownFile(2, lib.id, "Old/Elsewhere.aiff", None, None, None, True, False)
    r = run([lib], [unkeyed, keyed])
    assert r.moved == [(1, seen(lib, "Elsewhere.aiff"))]
    assert r.gone == [2]


def test_hidden_excluded_non_audio_and_links_are_skipped(lib, tmp_path):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, ".hidden/B.aiff", "b")
    put(lib.path, ".C.aiff", "c")
    put(lib.path, "notes.txt", "d")
    put(lib.path, "cover.JPG", "e")
    put(lib.path, "Loud.FLAC", "f")
    put(tmp_path, "Superseded/G.aiff", "g")
    put(lib.path, "Parked/H.aiff", "h")
    outside = put(tmp_path, "Outside/I.aiff", "i")
    (lib.path / "Link.aiff").symlink_to(outside)
    (lib.path / "LinkedDir").symlink_to(outside.parent, target_is_directory=True)
    root = WatchedFolder(1, tmp_path, "library")
    r = run([root], [], exclude=[tmp_path / "Superseded", tmp_path / "Library" / "Parked"])
    assert sorted(f.rel for f in r.new) == ["Library/A - One.aiff", "Library/Loud.FLAC", "Outside/I.aiff"]


def test_nested_watched_folders_are_scanned_once_as_the_outer_one(lib):
    inner = WatchedFolder(2, lib.path / "Imports", "import")
    put(lib.path, "A - One.aiff", "one")
    put(inner.path, "B - Two.aiff", "two")
    put(inner.path, "C - Three.aiff", "three")
    keys = Keys()
    r = run([lib, inner], [known(5, inner, "B - Two.aiff")], keys)
    assert r.unchanged == 1  # the inner folder's row matched where it is
    assert r.new == [seen(lib, "A - One.aiff"), seen(lib, "Imports/C - Three.aiff")]
    assert len(keys.calls) == 2  # each file once


def test_missing_folder_is_offline_and_its_rows_appear_nowhere(lib, tmp_path):
    usb = WatchedFolder(2, tmp_path / "Gone", "import")
    put(lib.path, "A - One.aiff", "one")
    rows = [known(1, lib, "A - One.aiff"), KnownFile(2, usb.id, "B.aiff", 3, 4, "k:b", True, False)]
    r = run([lib, usb], rows)
    assert r.offline == [2]
    assert r.gone == [] and r.unchanged == 1


def test_unmounted_volume_is_offline(lib):
    usb = WatchedFolder(2, Path("/Volumes/DJ-Stick/Music"), "import")
    asked = []
    r = run([lib, usb], [KnownFile(2, usb.id, "B.aiff", 3, 4, "k:b", True, False)],
            mounted=lambda p: asked.append(p) or False)
    assert asked == [Path("/Volumes/DJ-Stick")]
    assert r.offline == [2] and r.gone == []


def test_a_folder_is_away_for_one_of_two_reasons_and_offline_for_both(tmp_path):
    here = tmp_path / "Music"
    here.mkdir()
    drive = Path("/Volumes/DJ-Stick/Music")
    assert away_reason(here, lambda p: False) is None  # not under /Volumes: the mount check does not apply
    assert away_reason(tmp_path / "Renamed", lambda p: True) == "missing"
    assert away_reason(drive, lambda p: False) == "unmounted"  # the drive is not mounted, whatever is at the path
    assert away_reason(drive, lambda p: True) == "missing"  # mounted, but the folder is not on it
    assert not is_offline(here, lambda p: False)
    assert is_offline(drive, lambda p: False) and is_offline(tmp_path / "Renamed", lambda p: True)


def test_inner_folder_of_an_offline_folder_is_offline_too(tmp_path):
    outer = WatchedFolder(1, tmp_path / "Gone", "library")
    inner = WatchedFolder(2, tmp_path / "Gone" / "In", "import")
    r = run([outer, inner], [])
    assert sorted(r.offline) == [1, 2]


def test_folder_removed_mid_scan_becomes_offline_and_the_scan_goes_on(lib, tmp_path):
    usb = WatchedFolder(2, tmp_path / "Stick", "import")
    put(usb.path, "B.aiff", "b")
    put(usb.path, "C.aiff", "c")
    put(lib.path, "A - One.aiff", "one")
    stick_row = known(7, usb, "B.aiff")
    put(usb.path, "B.aiff", "b", mtime_ns=stick_row.mtime_ns + 10)  # needs a key, so the fake key runs

    def pull_out(path: Path) -> None:
        if usb.path in path.parents and usb.path.exists():
            shutil.rmtree(usb.path)

    keys = Keys(on_call=pull_out)
    r = run([lib, usb], [stick_row], keys)
    assert r.offline == [2]
    assert r.new == [seen(lib, "A - One.aiff")]
    assert r.retagged == [] and r.gone == [] and r.unreadable == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any folder")
def test_unlistable_subfolder_marks_nothing_gone(lib):
    put(lib.path, "Locked/A - One.aiff", "one")
    row = known(1, lib, "Locked/A - One.aiff")
    os.chmod(lib.path / "Locked", 0)
    try:
        r = run([lib], [row])
    finally:
        os.chmod(lib.path / "Locked", 0o755)
    assert r.gone == [] and r.offline == []
    assert r.unchanged == 1


def test_unreadable_file_is_listed_and_its_row_kept(lib):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    put(lib.path, "A - One.aiff", "one", mtime_ns=row.mtime_ns + 10)
    put(lib.path, "New.aiff", "new")

    def deny(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    r = run([lib], [row], Keys(on_call=deny))
    assert sorted(rel for _, rel, _ in r.unreadable) == ["A - One.aiff", "New.aiff"]
    assert all(folder == 1 and reason for folder, _, reason in r.unreadable)
    assert r.gone == [] and r.retagged == [] and r.new == []


def test_rels_are_nfc(lib):
    import unicodedata
    put(lib.path, unicodedata.normalize("NFD", "Café - Ü.aiff"), "x")
    r = run([lib], [])
    assert [f.rel for f in r.new] == [unicodedata.normalize("NFC", "Café - Ü.aiff")]


def test_missing_inner_folder_is_offline_not_gone(lib):
    inner = WatchedFolder(2, lib.path / "Imports", "import")
    put(lib.path, "A - One.aiff", "one")
    rows = [known(1, lib, "A - One.aiff"), KnownFile(2, inner.id, "B.aiff", 3, 4, "k:b", True, False)]
    r = run([inner, lib], rows)  # inner listed first: still scanned as part of the outer one
    assert r.offline == [2]
    assert r.gone == [] and r.unchanged == 1 and r.new == []


def test_missing_inner_folder_holds_rows_recorded_under_the_outer_one(lib):
    inner = WatchedFolder(2, lib.path / "Imports", "import")
    rows = [KnownFile(1, lib.id, "Imports/B.aiff", 3, 4, "k:b", True, False),  # found by an earlier scan
            KnownFile(2, lib.id, "C.aiff", 3, 4, "k:c", True, False)]
    r = run([lib, inner], rows)
    assert r.offline == [2]
    assert r.gone == [2]  # only the outer folder's own file


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any folder")
def test_a_file_moved_into_an_unlistable_subfolder_is_held(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "B - Two.aiff", "two")
    rows = [known(1, lib, "A - One.aiff"), known(2, lib, "B - Two.aiff")]
    (lib.path / "Locked").mkdir()
    (lib.path / "A - One.aiff").rename(lib.path / "Locked" / "A - One.aiff")
    (lib.path / "B - Two.aiff").rename(lib.path / "Seen.aiff")
    os.chmod(lib.path / "Locked", 0)
    try:
        r = run([lib], rows)
    finally:
        os.chmod(lib.path / "Locked", 0o755)
    assert r.held == [1] and r.gone == []
    assert r.moved == [(2, seen(lib, "Seen.aiff"))]  # a visible match still moves


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file's details")
def test_a_file_whose_details_cant_be_read_holds_the_folder_s_missing_rows(lib, tmp_path):
    other = WatchedFolder(2, tmp_path / "Other", "import")
    put(lib.path, "A - One.aiff", "one")
    put(other.path, "C.aiff", "c")
    rows = [known(1, lib, "A - One.aiff"), known(2, other, "C.aiff")]
    (lib.path / "A - One.aiff").unlink()
    (other.path / "C.aiff").unlink()
    put(lib.path, "Shut/X.aiff", "x")
    os.chmod(lib.path / "Shut", 0o444)  # listable, but its files' details can't be read
    try:
        r = run([lib, other], rows)
    finally:
        os.chmod(lib.path / "Shut", 0o755)
    assert [rel for _, rel, _ in r.unreadable] == ["Shut/X.aiff"]
    assert r.held == [1]
    assert r.gone == [2]  # another watched folder, seen in full


def test_an_unreadable_file_holds_only_missing_rows_of_its_size(lib):
    put(lib.path, "A - One.aiff", "same")
    put(lib.path, "B - Two.aiff", "a longer one")
    rows = [known(1, lib, "A - One.aiff"), known(2, lib, "B - Two.aiff")]
    (lib.path / "A - One.aiff").rename(lib.path / "Bad.aiff")
    (lib.path / "B - Two.aiff").unlink()

    def deny(path: Path) -> None:
        if path.name == "Bad.aiff":
            raise PermissionError(13, "Permission denied", str(path))

    r = run([lib], rows, Keys(on_call=deny))
    assert r.held == [1]
    assert r.gone == [2]


def test_default_key_is_the_content_key(lib):
    from discjockey.content_key import content_key
    p = put(lib.path, "A - One.mp3", "frames")
    r = scan([lib], [], exclude=[], snapshot_path=snap)
    assert r.new == [SeenFile(1, "A - One.mp3", p.stat().st_size, p.stat().st_mtime_ns, content_key(p))]


def test_a_song_s_missing_file_takes_its_one_indexed_copy(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "Copy/A - One.aiff", "one")  # copied, and indexed by a scan while the original was still there
    row, copy = known(1, lib, "A - One.aiff"), known(2, lib, "Copy/A - One.aiff", linked=False)
    (lib.path / "A - One.aiff").unlink()
    r = run([lib], [row, copy])
    assert r.moved == [(1, seen(lib, "Copy/A - One.aiff"))]
    assert r.gone == [] and r.ambiguous == [] and r.copies == []


def test_a_song_s_missing_file_with_two_indexed_copies_is_ambiguous(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "X/A - One.aiff", "one")
    put(lib.path, "Y/A - One.aiff", "one")
    rows = [known(1, lib, "A - One.aiff"), known(2, lib, "X/A - One.aiff", linked=False),
            known(3, lib, "Y/A - One.aiff", linked=False)]
    (lib.path / "A - One.aiff").unlink()
    r = run([lib], rows)
    assert r.ambiguous == [(1, ["1/X/A - One.aiff", "1/Y/A - One.aiff"])] and r.moved == [] and r.gone == []


def test_an_indexed_copy_and_a_new_copy_are_ambiguous(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "X/A - One.aiff", "one")
    rows = [known(1, lib, "A - One.aiff"), known(2, lib, "X/A - One.aiff", linked=False)]
    (lib.path / "A - One.aiff").rename(lib.path / "Y.aiff")
    r = run([lib], rows)
    assert r.ambiguous == [(1, ["1/X/A - One.aiff", "1/Y.aiff"])] and r.moved == [] and r.gone == []


def test_a_gone_unlinked_row_never_takes_an_indexed_copy(lib):
    put(lib.path, "A - One.aiff", "one")
    put(lib.path, "X/A - One.aiff", "one")
    rows = [known(1, lib, "A - One.aiff", linked=False), known(2, lib, "X/A - One.aiff", linked=False)]
    (lib.path / "A - One.aiff").unlink()
    r = run([lib], rows)
    assert r.gone == [1] and r.moved == []


def test_a_migrated_row_without_key_never_takes_an_indexed_file_by_name(lib):
    put(lib.path, "X/A - One.aiff", "other audio")
    rows = [KnownFile(1, lib.id, "A - One.aiff", None, None, None, True, False),
            known(2, lib, "X/A - One.aiff", linked=False)]
    r = run([lib], rows)
    assert r.gone == [1] and r.moved == []


def test_a_file_the_drive_lists_but_cannot_open_is_unreadable_not_skipped(lib, monkeypatch):
    put(lib.path, "Fine.aiff", "fine")
    put(lib.path, "Broken.aiff", "broken")
    real = os.lstat

    def lstat(path, *a, **kw):  # the directory lists "Broken.aiff", but looking at it fails
        if os.path.basename(path) == "Broken.aiff":
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", lstat)
    r = run([lib], [])
    assert [s.rel for s in r.new] == ["Fine.aiff"]
    assert r.unopenable == [(1, "Broken.aiff")]
    assert r.unreadable == [(1, "Broken.aiff", "The drive lists this file, but it can't be opened.")]


def test_a_file_removed_since_the_folder_was_listed_is_just_gone(lib, monkeypatch):
    put(lib.path, "Fine.aiff", "fine")
    put(lib.path, "Vanishing.aiff", "v")
    real = os.lstat

    def lstat(path, *a, **kw):  # removed between the listing and the look
        if os.path.basename(path) == "Vanishing.aiff":
            (lib.path / "Vanishing.aiff").unlink()
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", lstat)
    r = run([lib], [])
    assert [s.rel for s in r.new] == ["Fine.aiff"] and r.unreadable == [] and r.unopenable == []


def test_a_known_row_whose_entry_cannot_be_opened_is_kept_not_gone(lib, monkeypatch):
    put(lib.path, "A - One.aiff", "one")
    row = known(1, lib, "A - One.aiff")
    real = os.lstat

    def lstat(path, *a, **kw):
        if os.path.basename(path) == "A - One.aiff":
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", lstat)
    r = run([lib], [row])
    assert r.gone == [] and r.moved == [] and [rel for _, rel, _ in r.unreadable] == ["A - One.aiff"]
