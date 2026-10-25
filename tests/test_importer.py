"""importer.py: the import of the user's own music in two passes, stop and resume, offline and gone files, the
last linking phase (plan library stage 4, tasks 4.1-4.4)."""
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import TALB, TIT2, TPE1, TSRC

from audio_helpers import music, needs_ffmpeg, write_aiff
from discjockey import db, importer, library, run
from discjockey.events import CancelToken, ImportProgress
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.quality import AudioInfo
from discjockey.settings import SettingsError

pytestmark = needs_ffmpeg
NOW = datetime(2026, 10, 25, 12, 0, 0)


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path / "music", support=tmp_path / ".support")
    p.library.mkdir(parents=True)
    save_state(p, empty_state())
    return p


def add_folder(paths, folder):
    folder.mkdir(parents=True, exist_ok=True)
    with db.connect(paths.db_file) as conn:
        return db.add_watched_folder(conn, folder, NOW).id


def songs_folder(paths, tmp_path, n=5, name="Example Drive/Music"):
    """An import folder with n small AIFFs ("Example Artist - Song <i>.aiff"), watched."""
    folder = tmp_path / name
    folder.mkdir(parents=True)
    for i in range(1, n + 1):
        write_aiff(folder / f"Example Artist - Song {i}.aiff", music(1, seed=i))
    add_folder(paths, folder)
    return folder


class Fakes:
    """Stand-ins for the slow readers, counting their calls: every file is a lossless AIFF of 61 s with full
    sound, unless told otherwise."""

    def __init__(self):
        self.probed, self.inspected, self.linked = [], [], 0
        self.probe_fails, self.inspect_fails = set(), set()
        self.cutoff: dict[str, int] = {}
        self.on_probe = self.on_inspect = None

    def read_tags(self, path):
        return importer.read_tags(path)

    def probe(self, path):
        self.probed.append(path.name)
        if self.on_probe:
            self.on_probe(len(self.probed))
        if path.name in self.probe_fails:
            raise RuntimeError("ffprobe found no audio")
        return AudioInfo("pcm_s16be", 44100, 61.0)

    def inspect(self, path):
        self.inspected.append(path.name)
        if self.on_inspect:
            self.on_inspect(len(self.inspected))
        if path.name in self.inspect_fails:
            raise RuntimeError("ffmpeg could not decode it")
        return "pcm_s16be", self.cutoff.get(path.name)

    def link(self):
        self.linked += 1
        return None


def go(paths, fakes, token=None, events=None):
    return importer.run_import(paths, emit=(events.append if events is not None else lambda e: None),
                               token=token or CancelToken(), link=fakes.link, read_tags=fakes.read_tags,
                               probe=fakes.probe, inspect=fakes.inspect)


def own_entries(paths):
    return {k: e for k, e in load_state(paths)["tracks"].items() if k.startswith("local:")}


# --- 4.1 tags ---

def tone(path: Path, codec: list[str]) -> Path:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *codec, str(path)], check=True)
    return path


FORMATS = {".flac": ["-c:a", "flac"], ".m4a": ["-c:a", "aac"], ".aiff": ["-c:a", "pcm_s16be"],
           ".wav": ["-c:a", "pcm_s16le"]}


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_tags_are_read_from_every_format(tmp_path, ext):
    path = tone(tmp_path / f"x{ext}", FORMATS[ext])
    f = mutagen.File(path, easy=True)
    if ext in (".aiff", ".wav"):  # plain ID3, no easy keys
        f.add_tags()
        for frame in (TPE1(encoding=3, text=["Example Artist"]), TIT2(encoding=3, text=["Example Title"]),
                      TALB(encoding=3, text=["Example Album"]), TSRC(encoding=3, text=["XX0000000001"])):
            f.tags.add(frame)
    else:
        if f.tags is None:
            f.add_tags()
        f["artist"], f["title"], f["album"] = "Example Artist", "Example Title", "Example Album"
        if ext != ".m4a":  # MP4's easy tags have no ISRC
            f["isrc"] = "XX0000000001"
    f.save()
    tags = importer.read_tags(path)
    assert tags["artist"] == "Example Artist" and tags["title"] == "Example Title"
    assert tags["album"] == "Example Album"
    assert tags["isrc"] == (None if ext == ".m4a" else "XX0000000001")


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_missing_tags_are_none(tmp_path, ext):
    path = tone(tmp_path / f"x{ext}", [*FORMATS[ext], "-map_metadata", "-1"])
    assert importer.read_tags(path) == {"artist": None, "title": None, "album": None, "isrc": None}


def test_a_file_that_isnt_audio_has_no_tags_and_one_that_cant_be_opened_raises(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio at all" * 10)
    assert importer.read_tags(junk)["title"] is None
    with pytest.raises(FileNotFoundError):
        importer.read_tags(tmp_path / "gone.flac")


# --- 4.2 the two passes ---

def test_a_folder_of_five_files_becomes_five_own_songs_each_done(paths, tmp_path):
    songs_folder(paths, tmp_path)
    fakes, events = Fakes(), []
    fakes.cutoff["Example Artist - Song 2.aiff"] = 16000  # an MP3 made into an AIFF
    result = go(paths, fakes, events=events)
    assert result == importer.ImportResult(5, 5, 5, 0, 0, False, None)
    own = own_entries(paths)
    assert sorted(own) == [f"local:{i}" for i in range(1, 6)]
    by_title = {e["title"]: e for e in own.values()}
    assert {e["artist"] for e in own.values()} == {"Example Artist"}  # from the file names: no tags
    assert all(e["import_state"] == "done" and e["source"] == "manual" for e in own.values())
    assert by_title["Song 2"]["status"] == "fake_lossless" and by_title["Song 2"]["cutoff_hz"] == 16000
    assert by_title["Song 1"]["status"] == "lossless" and by_title["Song 1"]["duration_ms"] == 61000
    assert fakes.linked == 1
    phases = [(e.phase, e.done, e.total) for e in events if isinstance(e, ImportProgress)]
    assert phases[0] == ("scan", 0, 0)
    assert ("tags", 0, 5) in phases and ("tags", 5, 5) in phases
    assert ("sound", 0, 5) in phases and ("sound", 5, 5) in phases
    assert phases[-1] == ("link", 0, 0)


def test_after_pass_one_the_quality_is_the_codecs_and_the_sound_isnt_checked_yet(paths, tmp_path):
    songs_folder(paths, tmp_path, n=2)
    fakes = Fakes()
    fakes.probe = lambda path: (fakes.probed.append(path.name), AudioInfo("mp3", 44100, 200.0, 320))[1]
    token = CancelToken()
    fakes.on_inspect = lambda n: token.cancel()  # stop during the first sound check
    with pytest.raises(importer.ImportStopped) as stopped:
        go(paths, fakes, token)
    states = sorted((e["status"], e["import_state"]) for e in own_entries(paths).values())
    # the codec said lossy; the sound check judged the first file from its own sound (the fake: lossless PCM), the
    # second waits for it with the codec's quality (the Library's "sound not checked yet": "identified")
    assert states == [("lossless", "done"), ("not_lossless", "identified")]
    assert stopped.value.result.left == 1 and stopped.value.result.stopped
    assert fakes.linked == 0


def test_progress_comes_every_25_files_or_half_a_second(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(importer.time, "monotonic", lambda: clock[0])
    events = []
    pacer = importer._Pacer(events.append, "tags", 60, 0)
    for done in range(1, 61):
        pacer.step(done, 0)
    assert [e.done for e in events] == [0, 25, 50, 60]
    events.clear()
    pacer = importer._Pacer(events.append, "sound", 3, 0)
    for done in range(1, 3):
        clock[0] += 0.6
        pacer.step(done, 1)
    assert [(e.done, e.unreadable) for e in events] == [(0, 0), (1, 1), (2, 1)]


def test_an_empty_import_reads_nothing_and_links_nothing(paths, tmp_path):
    add_folder(paths, tmp_path / "Example Drive" / "Empty")
    fakes = Fakes()
    assert go(paths, fakes) == importer.ImportResult(0, 0, 0, 0, 0, False, None)
    assert fakes.linked == 0


# --- 4.3 stop and resume ---

def test_a_stop_in_pass_one_resumes_with_each_remaining_file_once(paths, tmp_path):
    songs_folder(paths, tmp_path)
    fakes, token = Fakes(), CancelToken()
    fakes.on_probe = lambda n: token.cancel() if n == 3 else None
    with pytest.raises(importer.ImportStopped) as stopped:
        go(paths, fakes, token)
    assert stopped.value.result == importer.ImportResult(3, 3, 0, 0, 5, True, None)
    assert len(fakes.probed) == 3 and fakes.inspected == []
    fakes.on_probe = None
    result = go(paths, fakes)
    assert len(fakes.probed) == 5 and sorted(fakes.probed) == sorted(set(fakes.probed))
    assert sorted(fakes.inspected) == sorted(fakes.probed)
    assert result == importer.ImportResult(5, 2, 5, 0, 0, False, None)
    assert len(own_entries(paths)) == 5


def test_a_stop_in_pass_two_resumes_with_each_remaining_file_once(paths, tmp_path):
    songs_folder(paths, tmp_path)
    fakes, token = Fakes(), CancelToken()
    fakes.on_inspect = lambda n: token.cancel() if n == 2 else None
    with pytest.raises(importer.ImportStopped) as stopped:
        go(paths, fakes, token)
    assert stopped.value.result.left == 3 and stopped.value.result.sound_checked == 2
    fakes.on_inspect = None
    result = go(paths, fakes)
    assert len(fakes.probed) == 5  # the tags are not read again
    assert len(fakes.inspected) == 5 and len(set(fakes.inspected)) == 5
    assert (result.files, result.own_songs, result.sound_checked, result.left) == (3, 0, 3, 0)
    assert {e["import_state"] for e in own_entries(paths).values()} == {"done"}


def test_an_unreadable_file_is_listed_then_tried_again_and_done(paths, tmp_path):
    folder = songs_folder(paths, tmp_path, n=3)
    fakes = Fakes()
    fakes.probe_fails.add("Example Artist - Song 2.aiff")
    first = go(paths, fakes)
    assert (first.files, first.own_songs, first.unreadable, first.left) == (2, 2, 1, 0)
    with db.connect(paths.db_file) as conn:
        assert db.import_unreadable(conn) == [(folder / "Example Artist - Song 2.aiff", importer.NO_SOUND)]
    fakes.probe_fails.clear()
    second = go(paths, fakes)
    assert (second.files, second.own_songs, second.unreadable) == (1, 1, 0)
    assert fakes.probed.count("Example Artist - Song 2.aiff") == 2
    with db.connect(paths.db_file) as conn:
        assert db.import_unreadable(conn) == []
    assert len(own_entries(paths)) == 3


def test_a_file_the_sound_check_cant_read_is_only_checked_again(paths, tmp_path):
    songs_folder(paths, tmp_path, n=2)
    fakes = Fakes()
    fakes.inspect_fails.add("Example Artist - Song 1.aiff")
    first = go(paths, fakes)
    assert (first.files, first.own_songs, first.sound_checked, first.unreadable) == (1, 2, 1, 1)
    fakes.inspect_fails.clear()
    probed = len(fakes.probed)
    second = go(paths, fakes)
    assert len(fakes.probed) == probed  # its tags were read: only the sound check is tried again
    assert (second.files, second.own_songs, second.sound_checked, second.unreadable) == (1, 0, 1, 0)
    assert {e["import_state"] for e in own_entries(paths).values()} == {"done"}


def test_no_access_is_worded_plainly(paths, tmp_path, monkeypatch):
    folder = songs_folder(paths, tmp_path, n=1)
    fakes = Fakes()

    def no_access(path):
        raise PermissionError(13, "Permission denied")
    fakes.read_tags = no_access
    assert go(paths, fakes).unreadable == 1
    with db.connect(paths.db_file) as conn:
        assert db.import_unreadable(conn) == [(folder / "Example Artist - Song 1.aiff", importer.NO_ACCESS)]


def test_a_stop_while_linking_is_a_stop_with_nothing_left(paths, tmp_path):
    songs_folder(paths, tmp_path, n=1)
    fakes, token = Fakes(), CancelToken()

    def link():
        token.cancel()
        token.check()
    fakes.link = link
    with pytest.raises(importer.ImportStopped) as stopped:
        go(paths, fakes, token)
    assert stopped.value.result.stopped and stopped.value.result.left == 0


# --- 4.4 offline and gone ---

def test_an_offline_folder_keeps_its_waiting_rows(paths, tmp_path):
    folder = songs_folder(paths, tmp_path, n=2)
    library.scan_library(paths, analyze=lambda p: ("pcm_s16be", None))
    shutil.move(folder, tmp_path / "unplugged")  # the drive is gone
    fakes = Fakes()
    result = go(paths, fakes)
    assert result == importer.ImportResult(0, 0, 0, 0, 0, False, None)
    assert fakes.probed == [] and fakes.linked == 0
    with db.connect(paths.db_file) as conn:
        assert [c.waiting for c in db.import_counts(conn).values()] == [2]
    assert importer.files_waiting(paths) == 0  # an offline drive's files never start an import
    shutil.move(tmp_path / "unplugged", folder)
    assert importer.files_waiting(paths) == 0  # until a scan sees the drive again
    assert go(paths, fakes).own_songs == 2


def test_a_file_gone_between_scan_and_pass_one_is_left_for_the_next_scan(paths, tmp_path, monkeypatch):
    folder = songs_folder(paths, tmp_path, n=3)
    gone = folder / "Example Artist - Song 2.aiff"
    scan = library.scan_library

    def scan_then_remove(*a, **kw):
        out = scan(*a, **kw)
        gone.unlink(missing_ok=True)
        return out
    monkeypatch.setattr(importer.library, "scan_library", scan_then_remove)
    fakes = Fakes()
    result = go(paths, fakes)
    assert (result.own_songs, result.unreadable, result.left) == (2, 0, 1)
    assert "Example Artist - Song 2.aiff" not in fakes.probed
    with db.connect(paths.db_file) as conn:
        assert db.import_unreadable(conn) == []
    monkeypatch.setattr(importer.library, "scan_library", scan)
    assert go(paths, fakes).left == 0  # the next scan knows it is gone: its row went


def test_files_waiting_counts_what_an_import_would_do(paths, tmp_path):
    assert importer.files_waiting(paths) == 0
    songs_folder(paths, tmp_path, n=2)
    library.scan_library(paths, analyze=lambda p: ("pcm_s16be", None))
    assert importer.files_waiting(paths) == 2


# --- the last phase ---

def test_link_playlists_reads_the_playlists_when_the_window_has_no_read(paths, monkeypatch):
    calls = []
    monkeypatch.setattr(run, "prepare", lambda p, **kw: calls.append("prepare") or "prep")
    monkeypatch.setattr(run, "link_only", lambda p, prep, emit: calls.append(("link_only", prep)))
    assert importer.link_playlists(paths) is None
    assert importer.link_playlists(paths, "window's read") is None
    assert calls == ["prepare", ("link_only", "prep"), ("link_only", "window's read")]


def test_link_playlists_leaves_linking_to_the_next_sync_when_the_playlists_cant_be_read(paths, monkeypatch):
    def offline(p, **kw):
        raise run.SetupProblem("No connection.", "offline")
    monkeypatch.setattr(run, "prepare", offline)
    monkeypatch.setattr(run, "link_only", lambda *a: pytest.fail("nothing is linked"))
    assert importer.link_playlists(paths) == importer.LINK_LATER


def test_the_link_note_reaches_the_result(paths, tmp_path):
    songs_folder(paths, tmp_path, n=1)
    fakes = Fakes()
    fakes.link = lambda: importer.LINK_LATER
    assert go(paths, fakes).link_note == importer.LINK_LATER


def test_the_words_at_the_end_take_a_singular_form():
    def words(files, left, stopped):
        return importer.result_words(importer.ImportResult(files, 0, 0, 0, left, stopped, None))
    assert words(1, 0, False) == "Imported 1 file."
    assert words(12, 0, False) == "Imported 12 files."
    assert words(3, 1, True) == "Import stopped with 1 file to go. It carries on where it stopped."
    assert words(3, 7, True) == "Import stopped with 7 files to go. It carries on where it stopped."


def test_a_stop_while_linking_links_at_the_next_import(paths, tmp_path):
    songs_folder(paths, tmp_path, n=1)
    fakes, token = Fakes(), CancelToken()

    def stop():
        token.cancel()
        token.check()
    fakes.link = stop
    with pytest.raises(importer.ImportStopped):
        go(paths, fakes, token)
    del fakes.link  # the class's counting link again
    result = go(paths, fakes)  # nothing to read, but the links are still to come
    assert (result.files, fakes.linked) == (0, 1)
    go(paths, fakes)
    assert fakes.linked == 1  # linked once: the next import has nothing to link


@pytest.mark.parametrize("problem", [library.StateError("playlists.txt is missing."),
                                     SettingsError("settings.json can't be read.")])
def test_playlists_that_cant_be_linked_say_why_and_keep_the_import(paths, monkeypatch, problem):
    def fails(p, prep, emit):
        raise problem
    monkeypatch.setattr(run, "link_only", fails)
    assert importer.link_playlists(paths, "window's read") == (
        f"Your playlists couldn't be linked yet: {str(problem).rstrip('.')}.")


def test_an_invalid_playlists_file_is_not_a_read_problem(paths, monkeypatch):
    def invalid(p, **kw):
        raise run.SetupProblem("Line 3 of playlists.txt isn't a playlist link.", "config_invalid")
    monkeypatch.setattr(run, "prepare", invalid)
    assert importer.link_playlists(paths) == (
        "Your playlists couldn't be linked yet: Line 3 of playlists.txt isn't a playlist link.")
