import importlib.util
import os
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
