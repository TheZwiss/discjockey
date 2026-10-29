import os
from datetime import datetime

import numpy as np
import pytest
from audio_helpers import SR, lowpass, music, needs_ffmpeg, pcm, write_aiff
from mutagen.aiff import AIFF

from discjockey import db, upgrades
from discjockey.align import Alignment, compare_files
from discjockey.audio import write_tags
from hub_helpers import records
from discjockey.library import Paths, empty_state, load_state, recover_pending, save_state
from discjockey.planner import ENTRY_KEYS
from discjockey.upgrades import UpgradeProblem

TID = "t1aaaaaaa"
CURRENT = "Library/A/not_lossless/Artist - Song.aiff"
ROOT_NAME = "Library/A/Artist - Song.aiff"
PARKED = "Upgrades ready/A/Artist - Song.aiff"
BACKUP = "Superseded/A/Artist - Song (lossy).aiff"
X = music(40)


def make_entry(path=CURRENT):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=40000, folder="A", path=path,
             status="not_lossless", source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=16000,
             rejected_sources=[], in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-10",
             upgrade={"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                      "found": "2026-10-10", "alignment": {"result": "shifted", "text": "x"}})
    return e


def setup_files(tmp_path, current_audio, parked_audio, path=CURRENT):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    for rel, audio in ((path, current_audio), (PARKED, parked_audio)):
        (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
        write_aiff(paths.root / rel, audio)
    write_tags(paths.root / PARKED, title="Song", artists=("Artist",), album="Album", isrc=None, label=None,
               cover=None, comment="Qobuz FLAC · verified lossless")
    state = empty_state()
    state["tracks"][TID] = make_entry(path)
    return paths, state


def up(state):
    return dict(state["tracks"][TID]["upgrade"])


def shifted(ms):
    n = round(ms * SR / 1000)
    return np.concatenate((np.zeros(n, np.float32), X)) if n > 0 else X[-n:]


# --- end to end with real audio ---

@needs_ffmpeg
def test_swap_keeps_the_file_and_moves_it_out_of_not_lossless(tmp_path):
    paths, state = setup_files(tmp_path, lowpass(X, 16000), shifted(23))  # new audio comes 23 ms later
    old_bytes = (paths.root / CURRENT).read_bytes()
    inode = os.stat(paths.root / CURRENT).st_ino
    r = upgrades.swap(paths, state, TID, up(state))

    final = paths.root / ROOT_NAME
    assert os.stat(final).st_ino == inode  # the same file: rekordbox keeps its entry, cues and beatgrid
    assert not (paths.root / CURRENT).exists()
    assert (paths.root / BACKUP).read_bytes() == old_bytes
    a = compare_files(paths.root / BACKUP, final)
    assert a.result == "exact" and a.offset_samples == 0  # the new audio now sits where the old audio was
    assert str(AIFF(str(final)).tags["TIT2"]) == "Song"
    assert AIFF(str(final)).tags.getall("COMM")[0].text == ["Qobuz FLAC · verified lossless"]
    assert not (paths.root / PARKED).exists() and not (paths.tmp / TID).exists()
    e = state["tracks"][TID]
    assert (e["status"], e["path"], e["source"], e["source_id"], e["source_format"], e["cutoff_hz"], e["upgrade"]) == (
        "lossless", ROOT_NAME, "qobuz", "q1", "flac", None, None)
    assert e["last_upgrade_check"] == "2026-10-10"
    assert state["pending"] == [] and records(load_state(paths)) == records(state)
    assert (r.section, r.path) == ("swapped", ROOT_NAME) and "23 ms" in r.note and BACKUP in r.note


@needs_ffmpeg
@pytest.mark.parametrize("ms", [23, -40])
def test_swap_shifts_the_new_audio_sample_exactly(tmp_path, ms):
    paths, state = setup_files(tmp_path, lowpass(X, 16000), shifted(ms))
    parked = pcm(paths.root / PARKED)
    upgrades.swap(paths, state, TID, up(state))
    out = pcm(paths.root / ROOT_NAME)
    n = round(ms * SR / 1000)
    if n > 0:
        assert np.array_equal(out, parked[n:])
    else:
        assert np.all(out[:-n] == 0) and np.array_equal(out[-n:], parked)


@needs_ffmpeg
def test_swap_stays_in_not_lossless_when_the_root_name_is_taken(tmp_path):
    paths, state = setup_files(tmp_path, lowpass(X, 16000), X)
    (paths.root / ROOT_NAME).write_bytes(b"a file of the user")
    inode = os.stat(paths.root / CURRENT).st_ino
    upgrades.swap(paths, state, TID, up(state))
    assert os.stat(paths.root / CURRENT).st_ino == inode
    assert state["tracks"][TID]["path"] == CURRENT
    assert (paths.root / ROOT_NAME).read_bytes() == b"a file of the user"
    assert compare_files(paths.root / BACKUP, paths.root / CURRENT).result == "exact"


@needs_ffmpeg
def test_swap_refused_when_the_versions_do_not_line_up(tmp_path):
    paths, state = setup_files(tmp_path, X, music(40, seed=9))
    before = (paths.root / CURRENT).read_bytes()
    with pytest.raises(UpgradeProblem, match="doesn't line up"):
        upgrades.swap(paths, state, TID, up(state))
    assert (paths.root / CURRENT).read_bytes() == before and (paths.root / PARKED).exists()
    assert not (paths.root / "Superseded").exists() and state["pending"] == []
    assert state["tracks"][TID]["upgrade"]


# --- refusals without audio ---

EXACT = Alignment("exact", 0, 0.0, 0.0, "matches exactly")
SHIFT = Alignment("shifted", 4, 0.091, 0.0, "lines up after shifting by 0 ms")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """Tiny byte files; build_staged writes the 'shifted' new audio without ffmpeg."""
    paths = Paths(tmp_path, support=tmp_path / ".support")
    for rel, data in ((CURRENT, b"old audio " * 1000), (PARKED, b"new audio " * 1000)):
        (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (paths.root / rel).write_bytes(data)
    state = empty_state()
    state["tracks"][TID] = make_entry()
    monkeypatch.setattr(upgrades, "build_staged", lambda parked, staged, n: staged.write_bytes(NEW))
    return paths, state


OLD, NEW = b"old audio " * 1000, b"NEW AUDIO " * 1200


def swap(paths, state, alignment=SHIFT):
    return upgrades.swap(paths, state, TID, up(state), compare=lambda cur, new: alignment)


def test_fake_swap_works(fake):
    paths, state = fake
    swap(paths, state)
    assert (paths.root / ROOT_NAME).read_bytes() == NEW and (paths.root / BACKUP).read_bytes() == OLD


@pytest.mark.parametrize("alignment", [Alignment("different", text="doesn't line up: a swap would shift your cue "
                                                                    "points"),
                                       Alignment("unknown", text="could not compare the two versions")])
def test_swap_refused_unless_swap_safe(fake, alignment):
    paths, state = fake
    with pytest.raises(UpgradeProblem, match="Not swapped"):
        swap(paths, state, alignment)
    assert (paths.root / CURRENT).read_bytes() == OLD and state["pending"] == []


def test_swap_refused_when_the_record_changed(fake):
    paths, state = fake
    shown = up(state)
    state["tracks"][TID]["upgrade"]["file"] = "Upgrades ready/A/other.aiff"
    with pytest.raises(UpgradeProblem, match="changed"):
        upgrades.swap(paths, state, TID, shown, compare=lambda cur, new: SHIFT)


def test_swap_refused_when_the_current_file_is_missing(fake):
    paths, state = fake
    (paths.root / CURRENT).unlink()
    with pytest.raises(UpgradeProblem, match="Run a sync first"):
        swap(paths, state)


def test_swap_with_the_parked_file_gone_clears_the_record(fake):
    paths, state = fake
    (paths.root / PARKED).unlink()
    with pytest.raises(UpgradeProblem) as err:
        swap(paths, state)
    assert err.value.forgotten and state["tracks"][TID]["upgrade"] is None


def test_swap_refused_for_a_wav_file(fake):
    paths, state = fake
    wav = "Library/A/not_lossless/Artist - Song.wav"
    (paths.root / CURRENT).rename(paths.root / wav)
    state["tracks"][TID]["path"] = wav
    with pytest.raises(UpgradeProblem, match="only works for AIFF"):
        swap(paths, state)
    assert not upgrades.swap_possible(state["tracks"][TID])


def test_a_failed_write_is_undone_at_once(fake, monkeypatch):
    paths, state = fake
    inode = os.stat(paths.root / CURRENT).st_ino
    real = upgrades._write_in_place

    def disk_full(target, source, sha):
        if source.name == "swap.aiff":
            with open(target, "r+b") as f:
                f.write(NEW[:500])
            raise OSError("No space left on device")
        real(target, source, sha)

    monkeypatch.setattr(upgrades, "_write_in_place", disk_full)
    with pytest.raises(UpgradeProblem, match="No space left.*undone"):
        swap(paths, state)
    assert (paths.root / CURRENT).read_bytes() == OLD and os.stat(paths.root / CURRENT).st_ino == inode
    assert state["pending"] == [] and state["tracks"][TID]["upgrade"] and (paths.root / PARKED).exists()


# --- crashes (the process dies: nothing catches it) and recovery at the next start ---

class Crash(BaseException):
    pass


def crash_in(monkeypatch, name, half=False):
    real = getattr(upgrades, name)

    def boom(*args, **kwargs):
        if half:  # _write_in_place(target, source, sha): half of the new content is on disk
            with open(args[0], "r+b") as f:
                f.write(args[1].read_bytes()[: len(NEW) // 2])
        raise Crash()

    monkeypatch.setattr(upgrades, name, boom)
    return real


def crash_and_reload(fake, monkeypatch, name, half=False):
    paths, state = fake
    real = crash_in(monkeypatch, name, half)
    with pytest.raises(Crash):
        swap(paths, state)
    monkeypatch.setattr(upgrades, name, real)
    on_disk = load_state(paths)
    assert on_disk["pending"] and on_disk["pending"][0]["kind"] == "swap"
    return paths, on_disk


def assert_swapped(paths, state, inode):
    assert (paths.root / ROOT_NAME).read_bytes() == NEW and os.stat(paths.root / ROOT_NAME).st_ino == inode
    assert (paths.root / BACKUP).read_bytes() == OLD
    assert state["tracks"][TID]["status"] == "lossless" and state["tracks"][TID]["path"] == ROOT_NAME
    assert state["pending"] == [] and not (paths.root / PARKED).exists()
    assert records(load_state(paths)) == records(state)


def assert_unchanged(paths, state, inode):
    assert (paths.root / CURRENT).read_bytes() == OLD and os.stat(paths.root / CURRENT).st_ino == inode
    assert state["tracks"][TID]["status"] == "not_lossless" and state["tracks"][TID]["upgrade"]
    assert state["pending"] == [] and (paths.root / PARKED).exists()


def test_crash_after_recording_the_step_starts_again_from_the_backup(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_back_up")
    assert not (paths.root / "Superseded").exists()
    [(message, ok)] = recover_pending(paths, state)
    assert ok and "Finished" in message
    assert_swapped(paths, state, inode)


def test_crash_after_recording_without_the_staged_file_changes_nothing(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_back_up")
    (paths.tmp / TID / "swap.aiff").unlink()
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "your file is as it was" in message
    assert_unchanged(paths, state, inode)


def test_crash_after_the_backup_rewrites_the_file(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_write_in_place")
    assert (paths.root / BACKUP).read_bytes() == OLD and (paths.root / CURRENT).read_bytes() == OLD
    recover_pending(paths, state)
    assert_swapped(paths, state, inode)


def test_crash_with_a_half_written_file_finishes_from_the_staged_copy(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_write_in_place", half=True)
    assert (paths.root / CURRENT).read_bytes() not in (OLD, NEW)
    [(message, ok)] = recover_pending(paths, state)
    assert ok
    assert_swapped(paths, state, inode)


def test_half_written_file_without_staged_copy_is_restored_from_the_backup(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_write_in_place", half=True)
    (paths.tmp / TID / "swap.aiff").unlink()
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "undone" in message and BACKUP in message
    assert_unchanged(paths, state, inode)
    assert (paths.root / BACKUP).read_bytes() == OLD  # the copy stays in Superseded/ (never deleted)


def test_crash_after_writing_finishes(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_finish")
    assert (paths.root / CURRENT).read_bytes() == NEW
    [(message, ok)] = recover_pending(paths, state)
    assert ok
    assert_swapped(paths, state, inode)


def test_crash_after_the_move_to_the_root_finishes(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "delete_parked")  # inside _finish, after the rename
    assert (paths.root / ROOT_NAME).read_bytes() == NEW and not (paths.root / CURRENT).exists()
    recover_pending(paths, state)
    assert_swapped(paths, state, inode)


def test_pending_swap_survives_clearing_tmp(fake, monkeypatch):
    from discjockey.library import clear_tmp
    paths, state = crash_and_reload(fake, monkeypatch, "_write_in_place", half=True)
    clear_tmp(paths, state)
    assert (paths.tmp / TID / "swap.aiff").exists()


def test_backup_and_new_content_are_written_out_before_going_on(fake, monkeypatch):
    """Power cut safety: the backup (file and its folder entry) is on the drive before the file is overwritten."""
    paths, state = fake
    events = []
    monkeypatch.setattr(upgrades, "full_fsync", lambda fd: events.append(("file", os.fstat(fd).st_ino)))
    monkeypatch.setattr(upgrades, "fsync_dir", lambda path: events.append(("dir", path)))
    target_ino = os.stat(paths.root / CURRENT).st_ino
    swap(paths, state)
    backup_ino = os.stat(paths.root / BACKUP).st_ino
    assert events == [("file", backup_ino), ("dir", paths.root / "Superseded/A"), ("file", target_ino)]


# --- the old audio is never overwritten without a verified backup in Superseded/ (review 2026-10-16) ---

FOREIGN = b"someone else's file"


def test_foreign_file_at_the_backup_name_changes_nothing(fake, monkeypatch):
    paths, state = fake
    inode = os.stat(paths.root / CURRENT).st_ino
    real = upgrades._back_up

    def name_taken_meanwhile(paths_, op):
        (paths_.root / op["backup"]).parent.mkdir(parents=True, exist_ok=True)
        (paths_.root / op["backup"]).write_bytes(FOREIGN)
        real(paths_, op)

    monkeypatch.setattr(upgrades, "_back_up", name_taken_meanwhile)
    with pytest.raises(UpgradeProblem, match="Nothing was changed"):
        swap(paths, state)
    assert_unchanged(paths, state, inode)
    assert (paths.root / BACKUP).read_bytes() == FOREIGN
    assert load_state(paths)["pending"] == [] and recover_pending(paths, state) == []


def test_a_failed_backup_changes_nothing(fake, monkeypatch):
    paths, state = fake
    inode = os.stat(paths.root / CURRENT).st_ino

    def disk_full(src, dst):
        raise OSError("No space left on device")

    monkeypatch.setattr(upgrades, "_copy_synced", disk_full)
    with pytest.raises(UpgradeProblem, match="No space left.*Nothing was changed"):
        swap(paths, state)
    assert_unchanged(paths, state, inode)
    assert not (paths.root / "Superseded").exists() and not (paths.tmp / TID).exists()


def test_crash_then_foreign_file_at_the_backup_name_backs_up_under_another_name(fake, monkeypatch):
    inode = os.stat(fake[0].root / CURRENT).st_ino
    paths, state = crash_and_reload(fake, monkeypatch, "_back_up")
    (paths.root / BACKUP).parent.mkdir(parents=True)
    (paths.root / BACKUP).write_bytes(FOREIGN)
    [(message, ok)] = recover_pending(paths, state)
    assert ok
    assert (paths.root / BACKUP).read_bytes() == FOREIGN
    assert (paths.root / "Superseded/A/Artist - Song (lossy) [t1aaaa].aiff").read_bytes() == OLD
    assert (paths.root / ROOT_NAME).read_bytes() == NEW and os.stat(paths.root / ROOT_NAME).st_ino == inode
    assert state["pending"] == [] and state["tracks"][TID]["status"] == "lossless"


def test_file_changed_before_the_backup_is_left_alone(fake, monkeypatch):
    paths, state = crash_and_reload(fake, monkeypatch, "_back_up")
    (paths.root / CURRENT).write_bytes(OLD + b"tag edit")  # e.g. rekordbox wrote a tag while Discjockey was down
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "left it alone" in message
    assert (paths.root / CURRENT).read_bytes() == OLD + b"tag edit"
    assert not (paths.root / "Superseded").exists() and state["pending"] == []
    assert state["tracks"][TID]["upgrade"] and (paths.root / PARKED).exists()


def test_backup_with_the_wrong_content_is_never_trusted(fake, monkeypatch):
    paths, state = crash_and_reload(fake, monkeypatch, "_write_in_place", half=True)
    half = (paths.root / CURRENT).read_bytes()
    (paths.root / BACKUP).write_bytes(b"damaged backup")
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "needs your help" in message
    assert (paths.root / CURRENT).read_bytes() == half  # not overwritten without a good backup
    assert state["pending"] and (paths.tmp / TID / "swap.aiff").exists()  # kept for the next start


@pytest.mark.parametrize("crash_at,content", [("_back_up", OLD), ("_write_in_place", b"a file of the user")],
                         ids=["before the backup", "after the backup"])
def test_a_file_at_the_root_name_is_never_written_into(fake, monkeypatch, crash_at, content):
    """The move to the folder root comes after the write: whatever sits there while the target is gone and the
    file is not the swapped one belongs to someone else."""
    paths, state = crash_and_reload(fake, monkeypatch, crash_at)
    (paths.root / CURRENT).rename(paths.tmp.parent / "moved away by the user.aiff")
    (paths.root / ROOT_NAME).write_bytes(content)
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "left it alone" in message
    assert (paths.root / ROOT_NAME).read_bytes() == content
    assert state["pending"] == [] and state["tracks"][TID]["upgrade"] and (paths.root / PARKED).exists()


def test_a_256_kbps_swap_keeps_the_file_in_not_lossless(fake):
    paths, state = fake
    state["tracks"][TID]["upgrade"].update(source="youtube_music", source_id="m1", source_format="aac",
                                           status="not_lossless", kbps=256, cutoff_hz=20000)
    r = swap(paths, state)
    e = state["tracks"][TID]
    assert (paths.root / CURRENT).read_bytes() == NEW and not (paths.root / ROOT_NAME).exists()
    assert (e["status"], e["path"], e["source_kbps"]) == ("not_lossless", CURRENT, 256)
    assert r.status == "not_lossless"


@needs_ffmpeg
def test_a_swap_in_any_playlist_folder_s_not_lossless_moves_up(tmp_path):
    # any direct child of Library/ is a playlist folder, in playlists.txt or not (spec §7)
    paths, state = setup_files(tmp_path, lowpass(X, 16000), X, path="Library/Z/not_lossless/Artist - Song.aiff")
    upgrades.swap(paths, state, TID, up(state))
    assert state["tracks"][TID]["path"] == "Library/Z/Artist - Song.aiff"
    assert (paths.root / "Superseded/Z/Artist - Song (lossy).aiff").exists()


@needs_ffmpeg
def test_a_swap_deeper_down_stays_where_the_file_is(tmp_path):
    deep = "Library/A/B/not_lossless/Artist - Song.aiff"
    paths, state = setup_files(tmp_path, lowpass(X, 16000), X, path=deep)
    inode = os.stat(paths.root / deep).st_ino
    upgrades.swap(paths, state, TID, up(state))
    assert state["tracks"][TID]["path"] == deep and os.stat(paths.root / deep).st_ino == inode
    assert (paths.root / "Superseded/A/B/not_lossless/Artist - Song (lossy).aiff").exists()


@needs_ffmpeg
def test_the_swap_backup_of_an_own_song_in_an_import_folder_mirrors_its_watched_folder(tmp_path, tmp_path_factory):
    watched = tmp_path_factory.mktemp("drive") / "Music"  # an import folder outside the music folder
    current = str(watched / "Sub" / "x.aiff")
    paths, state = setup_files(tmp_path, lowpass(X, 16000), shifted(23), path=current)
    own = {**state["tracks"].pop(TID), "source": "manual", "in_playlists": False}
    save_state(paths, empty_state())
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, watched, datetime(2026, 10, 25, 12, 0))
    state = load_state(paths)
    state["tracks"]["local:1"] = own
    old_bytes = (watched / "Sub" / "x.aiff").read_bytes()
    upgrades.swap(paths, state, "local:1", dict(own["upgrade"]))
    assert (paths.root / "Superseded/Music/Sub/x (lossy).aiff").read_bytes() == old_bytes  # spec §7, §10.5
    assert state["tracks"]["local:1"]["path"] == current  # swapped in place
