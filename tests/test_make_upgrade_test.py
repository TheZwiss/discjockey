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


def test_remove_takes_only_the_test_entry_and_no_file(root, capsys):
    assert script.main(["--root", str(root.root), ORIGINAL]) == 0
    files = sorted(p.relative_to(root.root) for p in root.root.rglob("*.aiff"))
    assert script.main(["--root", str(root.root), "--remove", "11qwPqW58QcUS4BaAclu0j"]) == 2  # not a test entry
    assert script.main(["--root", str(root.root), "--remove", "upgrade-test-1"]) == 0
    assert "Removed the test entry upgrade-test-1: Gimme Gimme (upgrade test)" in capsys.readouterr().out
    tracks = load_state(root)["tracks"]
    assert "upgrade-test-1" not in tracks and "11qwPqW58QcUS4BaAclu0j" in tracks
    assert sorted(p.relative_to(root.root) for p in root.root.rglob("*.aiff")) == files


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
    if path.suffix in (".aiff", ".mp3"):
        return str(f.tags["TPE1"]), str(f.tags["TIT2"])
    return f.tags["artist"][0], f.tags["title"][0]


@pytest.fixture
def library_only(tmp_path, monkeypatch):
    """An empty library and short click tracks (the click test needs no 40 s)."""
    monkeypatch.setattr(script, "CLICK_SECONDS", 12)
    paths = Paths(tmp_path / "music", support=tmp_path / ".support")
    paths.library.mkdir(parents=True)
    save_state(paths, empty_state())
    return paths


@pytest.mark.parametrize("kind, ext, codec, rate", [
    ("mp3", "mp3", "mp3", 44100), ("m4a48", "m4a", "aac", 48000), ("flac", "flac", "flac", 44100),
    ("aiff", "aiff", "pcm_s16be", 44100), ("aac", "m4a", "aac", 44100)])
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


def test_click_bpm_changes_the_spacing_of_the_clicks(library_only, tmp_path):
    for bpm, gap in ((90, 60 / 90), (150, 0.4)):
        assert script.main(["--root", str(library_only.root), "--click", "flac", "--bpm", str(bpm),
                            "--into", str(tmp_path / "scratch")]) == 0
        made = tmp_path / "scratch" / f"Click Test - Click flac {bpm} BPM (upgrade test).flac"
        assert abs(float(np.median(click_gaps(made))) - gap) < 0.06


def test_click_refuses_what_is_in_the_way(library_only, tmp_path, capsys):
    args = ["--root", str(library_only.root), "--click", "mp3"]
    assert script.main([*args, "--into", str(tmp_path / "scratch")]) == 0
    before = sorted(p.name for p in (tmp_path / "scratch").iterdir())
    assert script.main([*args, "--into", str(tmp_path / "scratch")]) == 2
    assert "already exists" in capsys.readouterr().out
    assert script.main([*args, "--into", str(library_only.library / "Mine")]) == 2  # a folder Discjockey watches
    assert "inside Library/" in capsys.readouterr().out
    assert script.main(["--root", str(library_only.root), "--click", "mp3", "--bpm", "5", "--into",
                        str(tmp_path / "other")]) == 2
    assert not (tmp_path / "other").exists() and sorted(p.name for p in (tmp_path / "scratch").iterdir()) == before
    for bad in (["--click", "mp3"], ["--same-edit", "--into", str(tmp_path)], ["--attach-upgrades", "--click", "mp3"]):
        with pytest.raises(SystemExit):
            script.main(["--root", str(library_only.root), *bad])
    with run_lock(library_only.lock):
        assert script.main([*args, "--into", str(tmp_path / "locked")]) == 3
    assert not (tmp_path / "locked").exists()


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


@pytest.mark.parametrize("kind", ["mp3", "m4a48"])
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
