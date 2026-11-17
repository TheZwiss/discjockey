import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from audio_helpers import music, needs_ffmpeg, pcm, write_aiff
from mutagen.aiff import AIFF

from discjockey import upgrades
from discjockey.align import Alignment, compare_files
from discjockey.audio import write_tags
from discjockey.library import Paths, empty_state, load_state, run_lock, save_state
from discjockey.planner import ENTRY_KEYS

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_upgrade_test.py"
spec = importlib.util.spec_from_file_location("make_upgrade_test", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

ORIGINAL = "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff"
TEST_STEM = "Vatoz Locoz - Gimme Gimme (upgrade test)"
CURRENT = f"Library/_Upgrade test/not_lossless/{TEST_STEM}.aiff"
PARKED = f"Upgrades ready/_Upgrade test/{TEST_STEM}.aiff"
pytestmark = needs_ffmpeg
# The app's own ffmpeg (what CI uses) has no MP3 encoder; a machine with one runs the MP3 cases.
needs_mp3 = pytest.mark.skipif(not script.encoder_available("libmp3lame"), reason="this ffmpeg has no MP3 encoder")


@pytest.fixture
def root(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    f = paths.root / ORIGINAL
    f.parent.mkdir(parents=True)
    write_aiff(f, music(40))
    write_tags(f, title="Gimme Gimme", artists=("Vatoz Locoz",), album="Album", isrc="DECE72605755", label=None,
               cover=None, comment="Qobuz FLAC · verified lossless")
    state = empty_state()
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], isrc="DECE72605755", artist="Vatoz Locoz", title="Gimme Gimme", duration_ms=40000,
             folder="Hard_Bounce", path=ORIGINAL, status="lossless", source="qobuz", source_id="123",
             source_format="flac", rejected_sources=[], in_playlists=True)
    state["tracks"]["11qwPqW58QcUS4BaAclu0j"] = e
    save_state(paths, state)
    return paths


def test_makes_a_separate_test_track_and_only_reads_the_original(root, capsys):
    before_bytes = (root.root / ORIGINAL).read_bytes()
    before_entry = load_state(root)["tracks"]["11qwPqW58QcUS4BaAclu0j"]
    inode = os.stat(root.root / ORIGINAL).st_ino
    assert script.main(["--root", str(root.root), ORIGINAL]) == 0

    assert (root.root / ORIGINAL).read_bytes() == before_bytes and os.stat(root.root / ORIGINAL).st_ino == inode
    state = load_state(root)
    assert state["tracks"]["11qwPqW58QcUS4BaAclu0j"] == before_entry and state["pending"] == []
    e = state["tracks"]["upgrade-test-1"]
    assert (e["artist"], e["title"], e["folder"], e["path"]) == (
        "Vatoz Locoz", "Gimme Gimme (upgrade test)", "_Upgrade test", CURRENT)
    assert (e["status"], e["source"], e["in_playlists"]) == ("not_lossless", "youtube_music", False)
    assert 15000 <= e["cutoff_hz"] < 19500  # clearly lossy (the lowpass is gentle: about 16.6 kHz)
    up = e["upgrade"]
    assert up["file"] == PARKED and (up["source"], up["source_id"]) == ("qobuz", "123")
    a = Alignment.from_dict(up["alignment"])
    assert a.result == "shifted" and abs(a.offset_ms + 30) < 0.1 and a.text == "lines up after shifting by 30 ms"
    assert np.array_equal(pcm(root.root / PARKED), pcm(root.root / ORIGINAL))  # same audio, only the title differs
    assert str(AIFF(str(root.root / PARKED)).tags["TIT2"]) == "Gimme Gimme (upgrade test)"
    assert "upgrade test copy" in AIFF(str(root.root / CURRENT)).tags.getall("COMM")[0].text[0]
    assert not (root.tmp / "upgrade-test").exists()
    out = capsys.readouterr().out
    assert "lines up after shifting by 30 ms" in out
    assert out.endswith("Test track id: upgrade-test-1 (you need it to remove the test again)\n")


def test_test_track_has_its_own_name_after_the_swap(root):
    """rekordbox finds missing files by name only, so the swapped test file must not share the original's name."""
    script.main(["--root", str(root.root), ORIGINAL])
    state = load_state(root)
    r = upgrades.swap(root, state, "upgrade-test-1", dict(state["tracks"]["upgrade-test-1"]["upgrade"]))
    final = f"Library/_Upgrade test/{TEST_STEM}.aiff"
    assert r.path == final and Path(final).name != Path(ORIGINAL).name
    assert compare_files(root.root / f"Superseded/_Upgrade test/{TEST_STEM} (lossy).aiff", root.root / final).result \
        == "exact"


def test_refuses_when_the_test_already_exists(root, capsys):
    assert script.main(["--root", str(root.root), ORIGINAL]) == 0
    before = load_state(root)
    assert script.main(["--root", str(root.root), ORIGINAL]) == 2
    assert "already exists" in capsys.readouterr().out
    assert load_state(root) == before


@pytest.mark.parametrize("source", ["Library/Hard_Bounce/missing.aiff", "Superseded/x.aiff"])
def test_refuses_other_files(root, source):
    assert script.main(["--root", str(root.root), source]) == 2


def test_waits_for_a_running_sync(root):
    with run_lock(root.lock):
        assert script.main(["--root", str(root.root), ORIGINAL]) == 3
    assert "upgrade-test-1" not in load_state(root)["tracks"]


def test_keep_lossy_m4a_makes_an_m4a_that_new_track_lines_up(root):
    """The stage A live check's test track (plan rekordbox stage A §8): the lossy copy stays an .m4a, and New track
    renders the AIFF where the M4A's audio sits (no rekordbox in tests: d = 0, so k = L)."""
    from mutagen.mp4 import MP4
    from discjockey.quality import probe
    assert script.main(["--root", str(root.root), ORIGINAL, "--keep-lossy", "m4a"]) == 0
    state = load_state(root)
    e = state["tracks"]["upgrade-test-1"]
    m4a = f"Library/_Upgrade test/not_lossless/{TEST_STEM}.m4a"
    assert (e["path"], e["source_format"]) == (m4a, "aac") and probe(root.root / m4a).codec == "aac"
    tags = MP4(str(root.root / m4a)).tags
    assert (tags["\xa9nam"], tags["\xa9ART"]) == (["Gimme Gimme (upgrade test)"], ["Vatoz Locoz"])
    a = Alignment.from_dict(e["upgrade"]["alignment"])
    assert a.result == "shifted" and abs(a.offset_ms + 30) < 0.1
    r = upgrades.add_new(root, state, "upgrade-test-1", dict(e["upgrade"]))
    check = state["tracks"]["upgrade-test-1"]["rekordbox_check"]
    assert check["aligned"] is True and check["undo"]["rendered"] is True
    lined_up = compare_files(root.root / f"Superseded/_Upgrade test/{TEST_STEM}.m4a", root.root / r.path)
    assert (lined_up.result, lined_up.offset_samples) == ("exact", 0)


# --- --clean / --all-marked ---

@pytest.fixture
def trash(tmp_path_factory, monkeypatch):
    """The Trash replaced by a recorder: a file goes to <a tmp folder outside the library>/<n>/ (the real Trash is
    never touched)."""
    folder = tmp_path_factory.mktemp("trash")
    calls = []

    def move_to_trash(path):
        calls.append(path)
        (folder / str(len(calls))).mkdir(parents=True)
        path.rename(folder / str(len(calls)) / path.name)

    monkeypatch.setattr(script, "trash_item", move_to_trash)
    move_to_trash.calls, move_to_trash.folder = calls, folder
    return move_to_trash


@pytest.fixture
def rekordbox_closed(monkeypatch):
    monkeypatch.setattr(script, "rekordbox_open", lambda: False)


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def everything(root_dir):
    return sorted(p.relative_to(root_dir).as_posix() for p in root_dir.rglob("*") if p.is_file())


@pytest.fixture
def messy(root, tmp_path):
    """The test track of `root` plus marked and unmarked files around it. Returns the scratch folder."""
    assert script.main(["--root", str(root.root), ORIGINAL]) == 0
    scratch = tmp_path / "scratch"
    for rel in (f"Superseded/_Upgrade test/{TEST_STEM} (lossy).aiff", "Library/Mine/Other - Song (upgrade test).mp3",
                "Upgrades ready/_Upgrade test/Other - Song (upgrade test).aiff"):
        touch(root.root / rel)
    for rel in ("Superseded/_Upgrade test/keep me.aiff", "Library/Mine/Plain - Song.mp3",
                "Library/_Upgrade test/not_lossless/no marker (upgrade).aiff"):
        touch(root.root / rel)
    for rel in ("Library/Mine/Song (UPGRADE TEST).mp3", "Library/Mine/Mine (upgrade test) remix.mp3"):
        touch(root.root / rel)  # a person's own names that only look like ours
    touch(scratch / "click_final (upgrade test).wav")
    touch(scratch / "my own track.wav")
    return scratch


def test_clean_all_marked_moves_only_the_marked_files_and_tidies(root, messy, trash, rekordbox_closed, capsys):
    marked = {f"Library/_Upgrade test/not_lossless/{TEST_STEM}.aiff", PARKED,
              f"Superseded/_Upgrade test/{TEST_STEM} (lossy).aiff", "Library/Mine/Other - Song (upgrade test).mp3",
              "Upgrades ready/_Upgrade test/Other - Song (upgrade test).aiff"}
    before = everything(root.root)
    assert script.main(["--root", str(root.root), "--all-marked", "--into", str(messy)]) == 0
    moved = {p.relative_to(root.root).as_posix() for p in trash.calls}
    assert moved == marked | {"scratch/click_final (upgrade test).wav"}
    assert sorted(p.name for p in trash.folder.rglob("*") if p.is_file()) == sorted(Path(m).name for m in moved)
    # everything without the marker stays, and the original's file untouched
    assert everything(root.root) == sorted(set(before) - moved) and (messy / "my own track.wav").exists()
    assert not (messy / "click_final (upgrade test).wav").exists()
    # the folders with nothing left go, the ones with a file in them stay
    assert not (root.root / "Upgrades ready/_Upgrade test").exists()
    assert (root.root / "Library/_Upgrade test/not_lossless/no marker (upgrade).aiff").exists()
    assert (root.root / "Library/Mine/Song (UPGRADE TEST).mp3").exists()  # not ours: another case ...
    assert (root.root / "Library/Mine/Mine (upgrade test) remix.mp3").exists()  # ... or the marker mid-name
    assert (root.root / "Superseded/_Upgrade test/keep me.aiff").exists()
    tracks = load_state(root)["tracks"]
    assert list(tracks) == ["11qwPqW58QcUS4BaAclu0j"]
    out = capsys.readouterr().out
    assert "Moved 6 file(s) to the Trash" in out and "Removed the test entry upgrade-test-1: Gimme Gimme (upgrade test)" in out
    assert "Removed the empty folder Upgrades ready/_Upgrade test" in out and "keep me" not in out
    assert out.rstrip().splitlines()[-1].startswith("Next: library scan")


def test_clean_one_entry_takes_only_the_files_of_its_song_and_answers_json(root, messy, trash, rekordbox_closed, capsys):
    assert script.main(["--root", str(root.root), "--clean", "upgrade-test-1", "--json"]) == 0
    answer = json.loads(capsys.readouterr().out)
    names = sorted(Path(p).name for p in answer["moved"])
    assert names == sorted([f"{TEST_STEM}.aiff", f"{TEST_STEM}.aiff", f"{TEST_STEM} (lossy).aiff"])
    assert all(Path(p).is_absolute() for p in answer["moved"]) and answer["ok"] is True
    assert answer["entries"] == ["upgrade-test-1"] and answer["next"][0]["run"] == "library scan"
    assert (root.root / "Library/Mine/Other - Song (upgrade test).mp3").exists()  # another test's file stays
    assert (messy / "click_final (upgrade test).wav").exists()  # and so does the scratch folder's (no --into anyway)
    assert (root.root / "Upgrades ready/_Upgrade test/Other - Song (upgrade test).aiff").exists()
    assert "upgrade-test-1" not in load_state(root)["tracks"]


def test_clean_refuses_what_it_should_and_changes_nothing(root, messy, trash, monkeypatch, capsys):
    before_files, before_state = everything(root.root), load_state(root)
    args = ["--root", str(root.root), "--all-marked", "--into", str(messy)]
    monkeypatch.setattr(script, "rekordbox_open", lambda: True)
    assert script.main(args) == 2
    assert "rekordbox is open" in capsys.readouterr().out
    assert script.main([*args, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    monkeypatch.setattr(script, "rekordbox_open", lambda: False)
    with run_lock(root.lock):
        assert script.main(args) == 3
    assert "still going" in capsys.readouterr().out
    # the id of a song of the library, an id nobody made, and a scratch folder that is not there
    for bad in (["--clean", "11qwPqW58QcUS4BaAclu0j"], ["--clean", "upgrade-test-9"],
                ["--all-marked", "--into", str(messy / "nope")]):
        assert script.main(["--root", str(root.root), *bad]) == 2
    for bad in (["--clean"], ["--clean", "upgrade-test-1", "--all-marked"], ["--json"], ["--all-marked", "--messy-name"]):
        with pytest.raises(SystemExit):
            script.main(["--root", str(root.root), *bad])
    assert not trash.calls and everything(root.root) == before_files and load_state(root) == before_state
    assert (messy / "click_final (upgrade test).wav").exists()


def test_clean_stops_when_the_trash_will_not_take_a_file_and_finishes_when_run_again(root, messy, trash, rekordbox_closed,
                                                                                    monkeypatch, capsys):
    real = script.trash_item
    count = []

    def fails_once(path):
        count.append(path)
        if len(count) == 2:
            raise OSError("the Trash is full")
        real(path)

    monkeypatch.setattr(script, "trash_item", fails_once)
    assert script.main(["--root", str(root.root), "--all-marked"]) == 2
    out = capsys.readouterr().out
    assert "could not be moved to the Trash (the Trash is full)" in out and "moved before it stopped" in out
    assert "upgrade-test-1" in load_state(root)["tracks"]  # the entry waits until the files are gone
    monkeypatch.setattr(script, "trash_item", real)
    assert script.main(["--root", str(root.root), "--all-marked"]) == 0
    assert "upgrade-test-1" not in load_state(root)["tracks"]
    assert len([p for p in trash.folder.rglob("*") if p.is_file()]) == 5  # all the marked files of Library/ etc.


def test_clean_without_anything_marked_says_so_and_still_names_the_scan(root, trash, rekordbox_closed, capsys):
    assert script.main(["--root", str(root.root), "--all-marked"]) == 0
    out = capsys.readouterr().out
    assert "No file with the marker was found." in out and "Next: library scan" in out
    assert (root.root / ORIGINAL).exists() and not trash.calls


def test_the_script_never_deletes_an_audio_file():
    """Files only ever go to the Trash: no `unlink`, `os.remove` or `rmtree` of a music file (rmtree only on the
    script's own work folder), however it is imported; the one `rmdir` empties folders in drop_empty_folders."""
    import ast
    tree = ast.parse(SCRIPT.read_text())
    banned = ("unlink", "remove", "rename", "replace", "rmtree")
    calls = [(n.lineno, n.func.attr) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert not [c for c in calls if c[1] in banned[:4]]
    assert not [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in banned]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "rmtree":
            assert ast.unparse(node.args[0]) == "work"
    rmdirs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "rmdir"]
    inside = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "drop_empty_folders")
    assert rmdirs and all(r in set(ast.walk(inside)) for r in rmdirs)


@pytest.mark.parametrize("name, ours", [
    ("Artist - Title (upgrade test).aiff", True), ("Artist - Title (upgrade test) (lossy).aiff", True),
    ("Artist - Title (upgrade test) (2).aiff", True), ("Artist - Title (upgrade test) [abc123].aiff", True),
    ("click_final (upgrade test).wav", True), ("Song (UPGRADE TEST).mp3", False),
    ("My Song (upgrade test) remix.mp3", False), ("Song (upgrade test)x.mp3", False), ("upgrade test.mp3", False),
    ("Song.(upgrade test)", False)])
def test_the_marker_is_matched_as_discjockeys_own_names_carry_it(name, ours):
    assert script.carries_marker(name) is ours


# --- the real trash_item (never the real Trash, never osascript) ---

class FakeFoundation:
    """A stand-in for pyobjc's Foundation: records what trashItemAtURL_resultingItemURL_error_ was asked."""

    def __init__(self, answer):
        self.calls = []
        fake = self

        class NSURL:
            @staticmethod
            def fileURLWithPath_(path):
                return ("url", path)

        class Manager:
            def trashItemAtURL_resultingItemURL_error_(self, url, result, error):
                fake.calls.append((url, result, error))
                return answer

        class NSFileManager:
            @staticmethod
            def defaultManager():
                return Manager()

        self.NSURL, self.NSFileManager = NSURL, NSFileManager


class FakeError:
    def localizedDescription(self):
        return "full"


def test_trash_item_asks_the_file_manager_and_raises_when_it_will_not(tmp_path, monkeypatch):
    f = touch(tmp_path / "a (upgrade test).wav")
    fake = FakeFoundation((True, None, None))
    monkeypatch.setitem(sys.modules, "Foundation", fake)
    script.trash_item(f)
    assert fake.calls == [(("url", str(f)), None, None)] and f.exists()  # asked once, with the file's path
    monkeypatch.setitem(sys.modules, "Foundation", FakeFoundation((False, None, FakeError())))
    with pytest.raises(OSError, match="full"):
        script.trash_item(f)
    monkeypatch.setitem(sys.modules, "Foundation", FakeFoundation((False, None, None)))
    with pytest.raises(OSError, match="Trash"):
        script.trash_item(f)


@pytest.mark.parametrize("code, stderr", [(0, ""), (1, "no")])
def test_trash_item_falls_back_to_the_finder_with_the_path_as_an_argument(tmp_path, monkeypatch, code, stderr):
    f = touch(tmp_path / 'we"ird -name (upgrade test).wav')
    monkeypatch.setitem(sys.modules, "Foundation", None)  # `import Foundation` fails
    runs = []

    def run(argv, **kw):
        runs.append(argv)
        return subprocess.CompletedProcess(argv, code, "", stderr)

    monkeypatch.setattr(script.subprocess, "run", run)
    if code:
        with pytest.raises(OSError, match="^no$"):
            script.trash_item(f)
    else:
        script.trash_item(f)
    (argv,) = runs
    assert argv[0] == "/usr/bin/osascript" and argv[-1] == str(f.absolute())
    assert argv[1::2][:-1] == ["-e"] * ((len(argv) - 2) // 2) and not any(str(f) in a for a in argv[:-1])
    assert f.exists()  # nothing was deleted by the script itself


def test_the_osascript_path_is_absolute_for_a_relative_file(tmp_path, monkeypatch):
    f = touch(tmp_path / "rel (upgrade test).wav")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "Foundation", None)
    runs = []
    monkeypatch.setattr(script.subprocess, "run", lambda argv, **kw: runs.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    script.trash_item(Path("rel (upgrade test).wav"))
    assert runs[0][-1] == str(f.absolute()) and Path(runs[0][-1]).is_absolute()


# --- the scratch folder of --into, a collision-tagged entry, rekordbox opened meanwhile ---

def test_clean_refuses_an_into_that_is_not_a_scratch_folder_of_its_own(root, messy, trash, rekordbox_closed, tmp_path,
                                                                       monkeypatch, capsys):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    touch(outside / "a (upgrade test).mp3")
    link = tmp_path / "scratchlink"
    link.symlink_to(outside, target_is_directory=True)
    home = tmp_path / "home"
    (home / "scratch2").mkdir(parents=True)
    monkeypatch.setattr(script.Path, "home", classmethod(lambda cls: home))
    before = everything(root.root)
    for bad in (link, home, tmp_path, tmp_path.parent, Path("/")):
        assert script.main(["--root", str(root.root), "--all-marked", "--into", str(bad)]) == 2, bad
        assert "is not a scratch folder of its own" in capsys.readouterr().out
    assert script.main(["--root", str(root.root), "--all-marked", "--into", str(home / "scratch2")]) == 0
    assert (outside / "a (upgrade test).mp3").exists() and not before == everything(root.root)
    assert all(p.name != "a (upgrade test).mp3" for p in trash.calls)


def test_clean_refusals_of_into_move_nothing(root, messy, trash, rekordbox_closed, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside2"
    touch(outside / "a (upgrade test).mp3")
    link = tmp_path / "scratchlink"
    link.symlink_to(outside, target_is_directory=True)
    before, state = everything(root.root), load_state(root)
    assert script.main(["--root", str(root.root), "--all-marked", "--into", str(link)]) == 2
    assert not trash.calls and everything(root.root) == before and load_state(root) == state


def test_the_walk_does_not_follow_a_symlinked_folder_inside_a_root(root, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside3"
    touch(outside / "a (upgrade test).mp3")
    (root.root / "Library" / "linked").symlink_to(outside, target_is_directory=True)
    found = script.marked_files([root.library])
    assert all("linked" not in p.parts for p in found)


def test_the_paths_moved_are_absolute_for_a_relative_into(root, messy, trash, rekordbox_closed, monkeypatch, capsys):
    monkeypatch.chdir(messy.parent)
    assert script.main(["--root", str(root.root), "--all-marked", "--into", "scratch", "--json"]) == 0
    moved = json.loads(capsys.readouterr().out)["moved"]
    assert moved and all(Path(p).is_absolute() for p in moved)
    assert str(messy.absolute() / "click_final (upgrade test).wav") in moved


def test_clean_one_entry_takes_the_files_of_a_collision_tagged_source(root, trash, rekordbox_closed):
    tagged = "Library/_Upgrade test/not_lossless/Artist - Title [abc123] (upgrade test).aiff"
    parked = "Upgrades ready/_Upgrade test/Artist - Title [abc123] (upgrade test).aiff"
    other = "Library/_Upgrade test/not_lossless/Artist - Other (upgrade test).aiff"
    for rel in (tagged, parked, other):
        touch(root.root / rel)
    state = load_state(root)
    e = dict(state["tracks"]["11qwPqW58QcUS4BaAclu0j"])
    e.update(artist="Artist", title="Title (upgrade test)", path=tagged, status="not_lossless",
             upgrade={"file": parked})
    state["tracks"]["upgrade-test-5"] = e
    save_state(root, state)
    assert script.main(["--root", str(root.root), "--clean", "upgrade-test-5"]) == 0
    assert sorted(p.relative_to(root.root).as_posix() for p in trash.calls) == sorted([tagged, parked])
    assert (root.root / other).exists() and "upgrade-test-5" not in load_state(root)["tracks"]


def test_rekordbox_opened_after_the_first_look_stops_before_any_file_moves(root, messy, trash, monkeypatch, capsys):
    looks = iter([False, True, True])
    monkeypatch.setattr(script, "rekordbox_open", lambda: next(looks))
    before, state = everything(root.root), load_state(root)
    assert script.main(["--root", str(root.root), "--all-marked", "--into", str(messy)]) == 2
    assert "rekordbox is open" in capsys.readouterr().out
    assert not trash.calls and everything(root.root) == before and load_state(root) == state


def test_rekordbox_is_looked_at_with_the_lock_held(root, messy, trash, monkeypatch):
    held = []

    def look():
        try:
            with run_lock(root.lock):
                held.append(False)
        except script.LockHeld:
            held.append(True)
        return False

    monkeypatch.setattr(script, "rekordbox_open", look)
    assert script.main(["--root", str(root.root), "--all-marked"]) == 0
    assert held and all(held)


def test_names_derived_from_a_marked_file_keep_the_marker(root):
    """So `--clean` finds what a New track, a Convert and a Give-it-its-clean-name make: the title tag carries the
    marker and the clean name is `Artist - Title.aiff` from the tags."""
    from discjockey import convert, rename
    assert script.main(["--root", str(root.root), ORIGINAL]) == 0
    state = load_state(root)
    e = state["tracks"]["upgrade-test-1"]
    new, old = upgrades.add_new_names(root, state, "upgrade-test-1", e, "lossless")
    assert Path(new).name == f"{TEST_STEM}.aiff" and script.SUFFIX in Path(old).name
    cnew, cold = convert.plan_file_names(root, state, "upgrade-test-1", e)
    assert script.SUFFIX in Path(cnew).name and script.SUFFIX in Path(cold).name
    snew, sold = convert.plan_names(root, state, "upgrade-test-1", e, dict(e["upgrade"]))
    assert script.SUFFIX in Path(snew).name and script.SUFFIX in Path(sold).name
    # a click track with a messy file name: its clean name is made from the tags, so it keeps the marker
    click = {**e, "artist": "Click Test", "title": "Click flac 120 BPM (upgrade test)", "status": "lossless",
             "path": "Library/_Upgrade test/click_final (upgrade test).aiff"}
    assert rename.clean_path(root, state, "upgrade-test-2", click) == \
        "Library/_Upgrade test/Click Test - Click flac 120 BPM (upgrade test).aiff"


# --- click tracks (--click, --attach-upgrades) ---

def decoded_mono(path, sr=44100):
    import subprocess
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le",
                        "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype="<f4")


def click_gaps(path, sr=44100):
    """The seconds between the starts of the loud bursts of a click track (the noise bed stays under 0.1)."""
    loud = np.flatnonzero(np.abs(decoded_mono(path, sr)) > 0.15)
    starts = loud[np.concatenate(([True], np.diff(loud) > 0.25 * sr))]
    return np.diff(starts) / sr


def artist_and_title(path):
    import mutagen
    f = mutagen.File(str(path))
    if path.suffix == ".m4a":
        return f.tags["\xa9ART"][0], f.tags["\xa9nam"][0]
    if path.suffix in (".aiff", ".mp3", ".wav"):
        return str(f.tags["TPE1"]), str(f.tags["TIT2"])
    return f.tags["artist"][0], f.tags["title"][0]


@pytest.fixture
def library_only(tmp_path, monkeypatch):
    """An empty library and short click tracks (the click test needs no 40 s)."""
    monkeypatch.setattr(script, "CLICK_SECONDS", 12)
    monkeypatch.setattr(script, "fdkaac_path", lambda: None)  # the ffmpeg path unless a test sets an fdkaac (CI has none)
    paths = Paths(tmp_path / "music", support=tmp_path / ".support")
    paths.library.mkdir(parents=True)
    save_state(paths, empty_state())
    return paths


@pytest.mark.parametrize("kind, ext, codec, rate", [
    pytest.param("mp3", "mp3", "mp3", 44100, marks=needs_mp3), ("m4a48", "m4a", "aac", 48000), ("flac", "flac", "flac", 44100),
    ("aiff", "aiff", "pcm_s16be", 44100), ("aac", "m4a", "aac", 44100), ("wav96", "wav", "pcm_s24le", 96000)])
def test_click_makes_a_decodable_track_with_the_marker_and_a_parked_upgrade(library_only, tmp_path, kind, ext, codec, rate):
    from discjockey.quality import probe
    into = tmp_path / "scratch"
    assert script.main(["--root", str(library_only.root), "--click", kind, "--into", str(into)]) == 0
    name = f"Click Test - Click {kind} 120 BPM (upgrade test).{ext}"
    made = into / name
    info = probe(made)
    assert (info.codec, info.sample_rate, info.channels) == (codec, rate, 2) and info.duration_s > 11.5
    assert artist_and_title(made) == ("Click Test", f"Click {kind} 120 BPM (upgrade test)")
    assert abs(float(np.median(click_gaps(made))) - 0.5) < 0.06  # 120 BPM
    parked = library_only.root / "Upgrades ready" / "_Upgrade test" / f"{made.stem}.aiff"
    up = probe(parked)
    assert (up.codec, up.sample_rate, up.channels) == ("pcm_s16be", 44100, 2)
    assert artist_and_title(parked) == artist_and_title(made)
    assert sorted(p.name for p in into.iterdir()) == [name]  # nothing else was made in the scratch folder
    assert not (library_only.tmp / "upgrade-test").exists()
    assert not load_state(library_only)["tracks"]  # the click track is no song of the library until it is imported


def test_click_aac_without_fdkaac_says_it_is_about_225_kbit_and_how_to_get_420(library_only, tmp_path, capsys):
    assert script.main(["--root", str(library_only.root), "--click", "aac", "--into", str(tmp_path / "scratch")]) == 0
    out = capsys.readouterr().out
    assert "only about 225 kbit/s" in out and "brew install fdk-aac-encoder" in out and "420" in out


@needs_ffmpeg
def test_click_aac_with_fdkaac_encodes_with_it_at_420_and_tags_the_file(library_only, tmp_path, monkeypatch, capsys):
    """A fake `fdkaac` (it logs its command line and has ffmpeg write the AAC) pins how the script calls the real one."""
    from discjockey.quality import probe
    log = tmp_path / "fdkaac.log"
    fake = tmp_path / "fdkaac"
    fake.write_text(f'#!/bin/sh\necho "$@" > "{log}"\nwhile [ "$1" != "-o" ]; do shift; done\n'
                    f'exec ffmpeg -nostdin -v error -y -i "$3" -c:a aac -b:a 128k -f ipod "$2"\n')
    fake.chmod(0o755)
    monkeypatch.setattr(script, "fdkaac_path", lambda: str(fake))
    into = tmp_path / "scratch"
    assert script.main(["--root", str(library_only.root), "--click", "aac", "--into", str(into)]) == 0
    made = into / "Click Test - Click aac 120 BPM (upgrade test).m4a"
    args = log.read_text().split()
    assert args[:2] == ["-b", "420000"] and args[2] == "-o" and args[4].endswith("click.wav")
    assert probe(made).codec == "aac" and artist_and_title(made) == ("Click Test", "Click aac 120 BPM (upgrade test)")
    out = capsys.readouterr().out
    assert "the AAC is 420 kbit/s (fdkaac)" in out and "225" not in out
    assert not (library_only.tmp / "upgrade-test").exists()


@needs_ffmpeg
@pytest.mark.skipif(not __import__("shutil").which("fdkaac"), reason="no fdkaac on PATH")
def test_click_aac_with_the_real_fdkaac_is_near_420_kbit(library_only, tmp_path, monkeypatch):
    from discjockey.quality import probe
    monkeypatch.undo()  # the fixture's fdkaac stub off: the real one on PATH
    monkeypatch.setattr(script, "CLICK_SECONDS", 12)
    into = tmp_path / "scratch"
    assert script.main(["--root", str(library_only.root), "--click", "aac", "--into", str(into)]) == 0
    info = probe(next(into.iterdir()))
    assert (info.codec, info.sample_rate) == ("aac", 44100) and 400 <= (info.stream_kbps or info.kbps) <= 440


@pytest.mark.parametrize("kind", ["aiff", "wav96"])
def test_click_messy_name_keeps_the_marker_in_the_name_and_the_tags(library_only, tmp_path, kind):
    from discjockey.quality import probe
    into = tmp_path / "scratch"
    assert script.main(["--root", str(library_only.root), "--click", kind, "--messy-name", "--into", str(into)]) == 0
    made = next(into.iterdir())
    assert made.stem == "click_final (upgrade test)"
    assert artist_and_title(made) == ("Click Test", f"Click {kind} 120 BPM (upgrade test)")  # the tags stay the same
    assert probe(made).duration_s > 11.5
    assert (library_only.root / "Upgrades ready/_Upgrade test/click_final (upgrade test).aiff").is_file()
    with pytest.raises(SystemExit):
        script.main(["--root", str(library_only.root), "--messy-name", "--attach-upgrades", "--into", str(into)])


def test_click_bpm_changes_the_spacing_of_the_clicks(library_only, tmp_path):
    for bpm, gap in ((90, 60 / 90), (150, 0.4)):
        assert script.main(["--root", str(library_only.root), "--click", "flac", "--bpm", str(bpm),
                            "--into", str(tmp_path / "scratch")]) == 0
        made = tmp_path / "scratch" / f"Click Test - Click flac {bpm} BPM (upgrade test).flac"
        assert abs(float(np.median(click_gaps(made))) - gap) < 0.06


def test_click_refuses_what_is_in_the_way(library_only, tmp_path, capsys):
    args = ["--root", str(library_only.root), "--click", "flac"]
    assert script.main([*args, "--into", str(tmp_path / "scratch")]) == 0
    before = sorted(p.name for p in (tmp_path / "scratch").iterdir())
    assert script.main([*args, "--into", str(tmp_path / "scratch")]) == 2
    assert "already exists" in capsys.readouterr().out
    assert script.main([*args, "--into", str(library_only.library / "Mine")]) == 2  # a folder Discjockey watches
    assert "inside Library/" in capsys.readouterr().out
    assert script.main(["--root", str(library_only.root), "--click", "flac", "--bpm", "5", "--into",
                        str(tmp_path / "other")]) == 2
    assert not (tmp_path / "other").exists() and sorted(p.name for p in (tmp_path / "scratch").iterdir()) == before
    for bad in (["--click", "flac"], ["--same-edit", "--into", str(tmp_path)], ["--attach-upgrades", "--click", "flac"]):
        with pytest.raises(SystemExit):
            script.main(["--root", str(library_only.root), *bad])
    with run_lock(library_only.lock):
        assert script.main([*args, "--into", str(tmp_path / "locked")]) == 3
    assert not (tmp_path / "locked").exists()


def test_click_without_the_encoder_says_which_is_missing_and_which_kinds_work(library_only, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(script, "encoder_available", lambda name: name != "libmp3lame")
    into = tmp_path / "scratch"
    assert script.main(["--root", str(library_only.root), "--click", "mp3", "--into", str(into)]) == 2
    out = capsys.readouterr().out.strip()
    assert out == ("This ffmpeg has no libmp3lame encoder, so --click mp3 cannot be made. "
                   "Kinds that work here: m4a48, flac, aiff, aac, wav96.")
    assert not into.exists() and not (library_only.root / "Upgrades ready").exists()


def test_encoder_available_reads_the_encoder_list_of_the_ffmpeg_on_path(monkeypatch):
    listing = " A....D aac                  AAC\n A....D libmp3lame           MP3 (codec mp3)\n"
    monkeypatch.setattr(script.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    script.encoder_available.cache_clear()
    try:
        assert script.encoder_available("libmp3lame") and script.encoder_available("aac")
        assert not script.encoder_available("pcm_s16be")
    finally:
        script.encoder_available.cache_clear()


def import_scratch(paths, folder):
    """`folder add` and the import of the scratch folder, with the real readers of tags and audio facts."""
    from datetime import datetime
    from discjockey import db, importer, quality
    from discjockey.events import CancelToken
    from discjockey.importer import read_tags
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 11, 16, 12, 0))
    importer.run_import(paths, token=CancelToken(), link=lambda: None, read_tags=read_tags, probe=quality.probe,
                        inspect=lambda p: (quality.probe(p).codec, None))
    return {e["title"]: (k, e) for k, e in load_state(paths)["tracks"].items()}


@pytest.mark.parametrize("kind", [pytest.param("mp3", marks=needs_mp3), "m4a48"])
@pytest.mark.parametrize("same_edit", [False, True])
def test_attach_parks_the_upgrade_on_the_imported_click_track(library_only, tmp_path, monkeypatch, capsys, kind,
                                                              same_edit):
    monkeypatch.setattr(script, "CLICK_SECONDS", 35)  # the alignment check needs 30 s
    scratch = tmp_path / "scratch"
    flags = ["--same-edit"] if same_edit else []
    assert script.main(["--root", str(library_only.root), "--click", kind, *flags, "--into", str(scratch)]) == 0
    assert script.main(["--root", str(library_only.root), "--attach-upgrades", "--into", str(scratch)]) == 2  # not imported yet
    assert "import it first" in capsys.readouterr().out
    songs = import_scratch(library_only, scratch)
    track_id, entry = songs[f"Click {kind} 120 BPM (upgrade test)"]
    assert entry["upgrade"] is None and entry["source"] == "manual"
    assert script.main(["--root", str(library_only.root), "--attach-upgrades", "--into", str(scratch)]) == 0
    assert f"Parked the lossless upgrade on {track_id}" in capsys.readouterr().out
    state = load_state(library_only)
    up = state["tracks"][track_id]["upgrade"]
    assert up["file"] == f"Upgrades ready/_Upgrade test/Click Test - Click {kind} 120 BPM (upgrade test).aiff"
    assert (library_only.root / up["file"]).is_file()
    measured = upgrades.check(library_only, state, track_id)  # the record is one the upgrade steps accept
    stored = Alignment.from_dict(up["alignment"])
    assert (stored.result, stored.offset_samples) == (measured.result, measured.offset_samples)
    # the same audio is "exact" to the sample; the default upgrade starts 30 ms later (1323 samples), a swap must shift
    assert (stored.result, stored.offset_samples) == (("exact", 0) if same_edit else ("shifted", 1323))
    # attached once only
    assert script.main(["--root", str(library_only.root), "--attach-upgrades", "--into", str(scratch)]) == 2
