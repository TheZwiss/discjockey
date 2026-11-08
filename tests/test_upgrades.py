import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg

from discjockey import upgrades
from discjockey.align import Alignment, unknown
from discjockey import library
from hub_helpers import records
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.planner import ENTRY_KEYS
from discjockey.upgrades import UpgradeProblem

EXACT = Alignment("exact", 0, 0.0, 0.0, "matches exactly")
CURRENT = "Library/A/not_lossless/Artist - Song.aiff"
PARKED = "Upgrades ready/A/Artist - Song.aiff"


def make_entry(folder="A", artist="Artist", title="Song", path=CURRENT, upgrade_file=PARKED, **kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, duration_ms=180000, folder=folder, path=path,
             status="not_lossless", source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=20100,
             rejected_sources=["qobuz:q0"], in_playlists=True, added="2026-10-01T10:00:00",
             last_attempt="2026-10-01", last_upgrade_check="2026-10-10")
    if upgrade_file:
        e["upgrade"] = {"file": upgrade_file, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                        "found": "2026-10-10", "alignment": EXACT.to_dict()}
    e.update(kw)
    return e


def touch(paths, rel, data):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


@pytest.fixture
def env(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    state = empty_state()
    state["tracks"]["t1aaaaaaa"] = make_entry()
    touch(paths, CURRENT, b"old audio")
    touch(paths, PARKED, b"new audio")
    return paths, state


def without_undo(check):
    """The check as the user reads it; its undo record is pinned in test_upgrade_undo.py."""
    return {k: v for k, v in check.items() if k != "undo"}


def up(state, tid="t1aaaaaaa"):
    return dict(state["tracks"][tid]["upgrade"])


def test_ready_lists_in_playlist_order_then_artist_and_title():
    s = empty_state()
    s["tracks"] = {
        "a": make_entry(folder="B", artist="zed"), "b": make_entry(folder="Old", artist="Abc"),
        "c": make_entry(folder="b", artist="Alpha", title="2"), "d": make_entry(folder="A", artist="Mid"),
        "e": make_entry(folder="A", upgrade_file=None), "f": make_entry(folder="B", artist="alpha", title="1"),
    }
    assert [k for k, _ in upgrades.ready(s, ["A", "B"])] == ["d", "f", "c", "a", "b"]


def test_discard_rejects_the_file_and_deletes_the_parked_copy(env):
    paths, state = env
    r = upgrades.discard(paths, state, "t1aaaaaaa", up(state))
    e = state["tracks"]["t1aaaaaaa"]
    assert e["upgrade"] is None and e["rejected_sources"] == ["qobuz:q0", "qobuz:q1"]
    assert e["status"] == "not_lossless" and e["path"] == CURRENT
    assert not (paths.root / PARKED).exists() and (paths.root / CURRENT).read_bytes() == b"old audio"
    assert records(load_state(paths)) == records(state)
    assert (r.section, r.track_id) == ("discarded", "t1aaaaaaa") and "Qobuz" in r.note


def test_discarding_a_better_stream_of_the_current_upload_does_not_mark_it_wrong(env):
    # a ~256 kbps stream through an account has the current file's own key: it is declined, not the wrong song
    paths, state = env
    state["tracks"]["t1aaaaaaa"]["upgrade"].update(source="youtube_music", source_id="y1", source_format="aac",
                                                   status="not_lossless", kbps=256, cutoff_hz=20000)
    upgrades.discard(paths, state, "t1aaaaaaa", up(state))
    e = state["tracks"]["t1aaaaaaa"]
    assert e["upgrade"] is None and e["rejected_sources"] == ["qobuz:q0"]
    assert e["declined_streams"] == ["youtube_music:y1"]
    assert records(load_state(paths)) == records(state)


def test_discard_works_without_the_current_file(env):
    paths, state = env
    (paths.root / CURRENT).unlink()
    upgrades.discard(paths, state, "t1aaaaaaa", up(state))
    assert state["tracks"]["t1aaaaaaa"]["upgrade"] is None


def test_add_as_new_file(env):
    paths, state = env
    r = upgrades.add_new(paths, state, "t1aaaaaaa", up(state), now=lambda: datetime(2026, 10, 16, 21, 0))
    e = state["tracks"]["t1aaaaaaa"]
    new = "Library/A/Artist - Song.aiff"  # the correct name; rekordbox's Auto Relocate links it by name
    assert (paths.root / new).read_bytes() == b"new audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert not (paths.root / CURRENT).exists() and not (paths.root / PARKED).exists()
    assert (e["status"], e["path"], e["source"], e["source_id"], e["source_format"], e["cutoff_hz"], e["upgrade"]) == (
        "lossless", new, "qobuz", "q1", "flac", None, None)
    assert e["last_upgrade_check"] == "2026-10-10" and e["rejected_sources"] == ["qobuz:q0"]
    assert without_undo(e["rekordbox_check"]) == {"reason": "added_as_new", "since": "2026-10-16", "match": "exact",
                                                  "offset_ms": 0.0, "aligned": False}
    # the parked measurement goes with it when the files can't be measured now (these aren't audio)
    assert state["pending"] == [] and records(load_state(paths)) == records(state)
    assert (r.section, r.path, r.status) == ("added_new", new, "lossless")


@pytest.mark.parametrize("alignment,match,offset", [
    (Alignment("shifted", -1014, -23.0, 0.2).to_dict(), "shifted", -23.0),
    (Alignment("different", drift_ms=412.5).to_dict(), "different", 0.0),
    (Alignment("unknown").to_dict(), "unknown", 0.0),
    (None, "unknown", 0.0),  # a parked version from before the measurement was kept
])
def test_add_as_new_file_keeps_the_parked_measurement_when_it_cant_measure_now(env, alignment, match, offset):
    paths, state = env
    upgrade = up(state)
    if alignment is None:
        upgrade.pop("alignment")
    else:
        upgrade["alignment"] = alignment
    upgrades.add_new(paths, state, "t1aaaaaaa", upgrade, compare=lambda cur, new: unknown(),
                     now=lambda: datetime(2026, 10, 16, 21, 0))
    assert without_undo(state["tracks"]["t1aaaaaaa"]["rekordbox_check"]) == {
        "reason": "added_as_new", "since": "2026-10-16", "match": match, "offset_ms": offset, "aligned": False}


def test_add_as_new_file_avoids_taken_names(env):
    paths, state = env
    touch(paths, "Library/A/Artist - Song.aiff", b"user file")
    touch(paths, "Superseded/A/Artist - Song.aiff", b"an older backup")
    upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/Artist - Song [t1aaaa].aiff"
    assert (paths.root / "Library/A/Artist - Song.aiff").read_bytes() == b"user file"
    assert (paths.root / "Superseded/A/Artist - Song [t1aaaa].aiff").read_bytes() == b"old audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"an older backup"


@pytest.mark.parametrize("action", ["add_new", "discard"])
def test_refused_when_the_upgrade_changed(env, action):
    paths, state = env
    shown = up(state)
    state["tracks"]["t1aaaaaaa"]["upgrade"]["source_id"] = "q2"  # e.g. replaced in the hub meanwhile
    with pytest.raises(UpgradeProblem, match="changed"):
        getattr(upgrades, action)(paths, state, "t1aaaaaaa", shown)
    assert (paths.root / PARKED).exists() and (paths.root / CURRENT).exists()


def test_add_as_new_file_refused_without_the_current_file(env):
    paths, state = env
    (paths.root / CURRENT).unlink()
    with pytest.raises(UpgradeProblem, match="Run a sync first"):
        upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    assert (paths.root / PARKED).exists() and state["tracks"]["t1aaaaaaa"]["upgrade"]


@pytest.mark.parametrize("action", ["add_new", "discard"])
def test_parked_file_gone_clears_the_record(env, action):
    paths, state = env
    (paths.root / PARKED).unlink()
    with pytest.raises(UpgradeProblem) as err:
        getattr(upgrades, action)(paths, state, "t1aaaaaaa", up(state))
    assert err.value.forgotten and "no longer in" in str(err.value)
    e = state["tracks"]["t1aaaaaaa"]
    assert e["upgrade"] is None and e["rejected_sources"] == ["qobuz:q0"]  # not rejected: it may come back
    assert load_state(paths)["tracks"]["t1aaaaaaa"]["upgrade"] is None


def test_check_measures_afresh(env):
    paths, state = env
    calls = []
    a = upgrades.check(paths, state, "t1aaaaaaa", compare=lambda cur, new: calls.append((cur, new)) or EXACT)
    assert a == EXACT and calls == [(paths.root / CURRENT, paths.root / PARKED)]


def test_check_without_the_current_file(env):
    paths, state = env
    (paths.root / CURRENT).unlink()
    with pytest.raises(UpgradeProblem, match="Run a sync first"):
        upgrades.check(paths, state, "t1aaaaaaa", compare=lambda cur, new: EXACT)


def test_drop_parked(env):
    paths, state = env
    e = upgrades.drop_parked(paths, state["tracks"]["t1aaaaaaa"])
    assert e["upgrade"] is None and not (paths.root / PARKED).exists()
    assert state["tracks"]["t1aaaaaaa"]["upgrade"]  # the caller decides when to store it


def test_discard_deletes_the_parked_file_before_saving(env, monkeypatch):
    """A crash in between must not leave a parked file nobody knows about (a missing one is handled)."""
    paths, state = env
    seen = []
    real = upgrades.save_state
    monkeypatch.setattr(upgrades, "save_state",
                        lambda path, s: seen.append((paths.root / PARKED).exists()) or real(path, s))
    upgrades.discard(paths, state, "t1aaaaaaa", up(state))
    assert seen == [False]


ROOT_NAME = "Library/A/Artist - Song.aiff"


@pytest.fixture
def at_root(env):
    """The current (lossy) file already has the correct name in the folder root."""
    paths, state = env
    (paths.root / CURRENT).rename(paths.root / ROOT_NAME)
    state["tracks"]["t1aaaaaaa"]["path"] = ROOT_NAME
    return paths, state


def test_add_as_new_when_the_old_file_has_the_name_moves_it_away_first(at_root):
    paths, state = at_root
    r = upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    assert (r.path, state["tracks"]["t1aaaaaaa"]["path"]) == (ROOT_NAME, ROOT_NAME)
    assert (paths.root / ROOT_NAME).read_bytes() == b"new audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert state["pending"] == [] and not (paths.root / PARKED).exists()


@pytest.mark.parametrize("renames_done", [0, 1, 2])
def test_add_as_new_at_the_old_name_is_crash_safe(at_root, monkeypatch, renames_done):
    paths, state = at_root

    def power_off(paths_, state_, track_id, renames, entry):  # run_op, cut off after `renames_done` renames
        state_.setdefault("pending", []).append({"track_id": track_id, "renames": [list(r) for r in renames],
                                                 "entry": entry})
        save_state(paths_, state_)
        for src, dst in renames[:renames_done]:
            library.safe_rename(paths_.root, src, dst)
        raise KeyboardInterrupt

    monkeypatch.setattr(upgrades, "run_op", power_off)
    with pytest.raises(KeyboardInterrupt):
        upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    state = load_state(paths)
    messages = library.recover_pending(paths, state)
    e = state["tracks"]["t1aaaaaaa"]
    assert messages[0][1] is True and state["pending"] == []
    assert (e["path"], e["status"], e["upgrade"]) == (ROOT_NAME, "lossless", None)
    assert (paths.root / ROOT_NAME).read_bytes() == b"new audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"


def lossy_up(state, tid="t1aaaaaaa"):
    state["tracks"][tid]["upgrade"].update(source="youtube_music", source_id="m1", source_format="aac",
                                           status="not_lossless", kbps=256, cutoff_hz=20000)
    return up(state, tid)


def test_upgrade_name():
    assert upgrades.upgrade_name({"source": "qobuz"}) == "lossless version"
    assert upgrades.upgrade_name({"status": "not_lossless", "kbps": 256}) == "256 kbps version"


def test_a_256_kbps_version_added_as_new_stays_lossy(env):
    paths, state = env
    r = upgrades.add_new(paths, state, "t1aaaaaaa", lossy_up(state), now=lambda: datetime(2026, 10, 16, 21, 0))
    e = state["tracks"]["t1aaaaaaa"]
    new = "Library/A/not_lossless/Artist - Song.aiff"  # the old file left this name in the same step
    assert (paths.root / new).read_bytes() == b"new audio"
    assert (e["status"], e["path"], e["source"], e["source_kbps"], e["cutoff_hz"]) == (
        "not_lossless", new, "youtube_music", 256, 20000)
    assert (r.section, r.status) == ("added_new", "not_lossless")


def test_messages_name_the_256_kbps_version(env):
    paths, state = env
    record = lossy_up(state)
    (paths.root / PARKED).unlink()
    with pytest.raises(UpgradeProblem, match="256 kbps version"):
        upgrades.add_new(paths, state, "t1aaaaaaa", record)


def test_add_as_new_for_a_file_kept_elsewhere_lands_next_to_it(env):
    paths, state = env  # option A (spec §7): the user owns where the file lives
    touch(paths, "Library/Sets/2024/x.aiff", b"old audio")
    (paths.root / CURRENT).unlink()
    state["tracks"]["t1aaaaaaa"]["path"] = "Library/Sets/2024/x.aiff"
    r = upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    assert r.path == state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.aiff"
    assert (paths.root / "Library/Sets/2024/Artist - Song.aiff").read_bytes() == b"new audio"
    assert (paths.root / "Superseded/Sets/2024/x.aiff").read_bytes() == b"old audio"


def test_add_as_new_for_an_own_song_in_an_import_folder_supersedes_into_its_watched_folders_mirror(tmp_path,
                                                                                                 tmp_path_factory):
    from discjockey import db
    paths = Paths(tmp_path, support=tmp_path / ".support")
    save_state(paths, empty_state())
    music = tmp_path_factory.mktemp("drive") / "Music"  # an import folder outside the music folder
    current = str(music / "Sub" / "x.aiff")
    touch(paths, current, b"old audio")
    touch(paths, "Upgrades ready/Music/Sub/Artist - Song.aiff", b"new audio")
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, music, datetime(2026, 10, 25, 12, 0))
    state = load_state(paths)
    state["tracks"]["local:1"] = make_entry(path=current, upgrade_file="Upgrades ready/Music/Sub/Artist - Song.aiff",
                                            source="manual", in_playlists=False)
    upgrades.add_new(paths, state, "local:1", up(state, "local:1"))
    assert (paths.root / "Superseded/Music/Sub/x.aiff").read_bytes() == b"old audio"  # spec §7, §10.5
    assert (music / "Sub" / "Artist - Song.aiff").read_bytes() == b"new audio"


# --- New track lined up with rekordbox's timeline (plan rekordbox stage A §1.9) ---

SHIFT = Alignment("shifted", 1014, 23.0, 0.0, "lines up after shifting by 23 ms")
NEW_NAME = "Library/A/Artist - Song.aiff"


def timing(d):
    """A stand-in for rekordbox.timeline_offset that answers `d` (44.1 kHz samples; None: unknown) for any file."""
    seen = []

    def offset(old_file):
        seen.append(old_file)
        return SimpleNamespace(samples=d)
    offset.seen = seen
    return offset


def add(paths, state, compare=EXACT, offset=None, tid="t1aaaaaaa"):
    return upgrades.add_new(paths, state, tid, up(state, tid), compare=lambda cur, new: compare, offset=offset,
                            now=lambda: datetime(2026, 11, 8, 12, 0))


def test_same_edit_with_a_zero_shift_is_renamed_and_lined_up(env):
    paths, state = env
    offset = timing(0)
    add(paths, state, EXACT, offset)
    e = state["tracks"]["t1aaaaaaa"]
    assert offset.seen == [paths.root / CURRENT]  # rekordbox's timing of the old file
    assert (paths.root / NEW_NAME).read_bytes() == b"new audio"  # k == 0: the download itself, no copy
    assert without_undo(e["rekordbox_check"])["aligned"] is True and "held" not in e["rekordbox_check"]["undo"]
    assert not paths.undo.exists() and not (paths.tmp / "t1aaaaaaa").exists()


@pytest.mark.parametrize("compare,offset", [
    (Alignment("different", drift_ms=412.5), timing(0)),  # a different edit: rekordbox isn't asked
    (unknown(), timing(0)),
    (SHIFT, timing(None)),  # rekordbox's timing unknown (not analysed, timing, unreadable)
])
def test_without_a_known_shift_new_track_is_renamed_as_before(env, compare, offset):
    paths, state = env
    add(paths, state, compare, offset)
    assert offset.seen == ([paths.root / CURRENT] if compare.swap_safe else [])
    assert (paths.root / NEW_NAME).read_bytes() == b"new audio"
    assert without_undo(state["tracks"]["t1aaaaaaa"]["rekordbox_check"])["aligned"] is False


def test_an_old_file_ffmpeg_cant_read_is_renamed_as_before(env):
    def unreadable(old_file):
        raise RuntimeError("ffmpeg could not decode it")

    paths, state = env
    add(paths, state, SHIFT, unreadable)
    assert (paths.root / NEW_NAME).read_bytes() == b"new audio"
    assert without_undo(state["tracks"]["t1aaaaaaa"]["rekordbox_check"])["aligned"] is False


def test_the_measurement_made_now_wins_over_the_parked_one(env):
    paths, state = env
    add(paths, state, Alignment("different", drift_ms=300.0), timing(0))  # parked as exact
    assert state["tracks"]["t1aaaaaaa"]["rekordbox_check"]["match"] == "different"


def test_a_render_that_fails_changes_nothing(env):
    paths, state = env  # the download isn't audio: ffmpeg refuses it
    before = load_state(paths) if paths.db_file.exists() else None
    with pytest.raises(UpgradeProblem, match="Nothing was changed; the lossless version is still waiting"):
        add(paths, state, SHIFT, timing(0))
    assert (paths.root / CURRENT).read_bytes() == b"old audio" and (paths.root / PARKED).read_bytes() == b"new audio"
    assert not (paths.root / NEW_NAME).exists() and not (paths.root / "Superseded").exists()
    assert not (paths.tmp / "t1aaaaaaa").exists() and not paths.undo.exists()
    assert state["tracks"]["t1aaaaaaa"]["upgrade"] and state["pending"] == []
    assert before is None or records(load_state(paths)) == records(before)


@pytest.mark.parametrize("renames_done", [0, 1, 2, 3])
def test_a_rendered_add_is_crash_safe(env, monkeypatch, renames_done):
    paths, state = env
    monkeypatch.setattr(upgrades, "build_staged", lambda parked, staged, n: staged.write_bytes(b"rendered audio"))

    def power_off(paths_, state_, track_id, renames, entry):  # run_op, cut off after `renames_done` renames
        state_.setdefault("pending", []).append({"track_id": track_id, "renames": [list(r) for r in renames],
                                                 "entry": entry})
        save_state(paths_, state_)
        for src, dst in renames[:renames_done]:
            library.safe_rename(paths_.root, src, dst)
        raise KeyboardInterrupt

    monkeypatch.setattr(upgrades, "run_op", power_off)
    with pytest.raises(KeyboardInterrupt):
        add(paths, state, SHIFT, timing(0))
    assert (paths.tmp / "t1aaaaaaa" / "new.aiff").exists() == (renames_done < 2)  # kept: the step names it
    state = load_state(paths)
    library.clear_tmp(paths, state)  # the next start keeps what the pending step names
    messages = library.recover_pending(paths, state)
    e = state["tracks"]["t1aaaaaaa"]
    assert messages[0][1] is True and state["pending"] == []
    assert (e["path"], e["status"], e["upgrade"]) == (NEW_NAME, "lossless", None)
    assert (paths.root / NEW_NAME).read_bytes() == b"rendered audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert (paths.root / e["rekordbox_check"]["undo"]["held"]).read_bytes() == b"new audio"
    library.clear_tmp(paths, state)
    assert not (paths.tmp / "t1aaaaaaa").exists()


def test_a_rendered_add_reaches_an_import_folder_on_another_drive(tmp_path, tmp_path_factory, monkeypatch):
    from discjockey import db
    paths = Paths(tmp_path, support=tmp_path / ".support")
    save_state(paths, empty_state())
    music = tmp_path_factory.mktemp("drive") / "Music"  # an import folder on "another drive"
    monkeypatch.setattr(library, "device", lambda p: 2 if Path(p).is_relative_to(music) else 1)
    monkeypatch.setattr(upgrades, "build_staged", lambda parked, staged, n: staged.write_bytes(b"rendered audio"))
    current = str(music / "Sub" / "x.aiff")
    touch(paths, current, b"old audio")
    touch(paths, "Upgrades ready/Music/Sub/Artist - Song.aiff", b"new audio")
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, music, datetime(2026, 10, 25, 12, 0))
    state = load_state(paths)
    state["tracks"]["local:1"] = make_entry(path=current, upgrade_file="Upgrades ready/Music/Sub/Artist - Song.aiff",
                                            source="manual", in_playlists=False)
    add(paths, state, SHIFT, timing(0), tid="local:1")
    assert (music / "Sub" / "Artist - Song.aiff").read_bytes() == b"rendered audio"  # copied, checked, then placed
    assert not any(p.name.startswith(".") for p in (music / "Sub").iterdir())  # no staged copy left
    assert (paths.root / "Superseded/Music/Sub/x.aiff").read_bytes() == b"old audio"
    assert not (paths.tmp / "local:1").exists() and state["pending"] == []


# --- with real audio ---

@needs_ffmpeg
def test_new_track_renders_the_same_edit_lined_up_with_an_aiff(tmp_path):
    from audio_helpers import lowpass, music, pcm, write_aiff
    from discjockey.audio import write_tags
    from discjockey.rekordbox import timeline_offset
    x = music(40)  # long enough for align to measure
    paths = Paths(tmp_path, support=tmp_path / ".support")
    (paths.root / CURRENT).parent.mkdir(parents=True)
    (paths.root / PARKED).parent.mkdir(parents=True)
    write_aiff(paths.root / CURRENT, lowpass(x, 16000))
    write_aiff(paths.root / PARKED, np.concatenate([np.zeros(1014, np.float32), x]))  # 23 ms later
    write_tags(paths.root / PARKED, title="Song", artists=("Artist",), album="Album", isrc=None, label=None,
               cover=None, comment="Qobuz FLAC · verified lossless")
    state = empty_state()
    state["tracks"]["t1aaaaaaa"] = make_entry()
    parked = pcm(paths.root / PARKED)
    r = upgrades.add_new(paths, state, "t1aaaaaaa", up(state))  # the defaults: measured now, rekordbox asked
    assert timeline_offset(paths.root / "Superseded/A/Artist - Song.aiff").why == "no_rekordbox"  # conftest: none
    assert np.array_equal(pcm(paths.root / NEW_NAME), parked[1014:])  # L = 1014, d = 0
    assert str(AIFF(str(paths.root / NEW_NAME)).tags["TIT2"]) == "Song"  # the download's tags
    check = state["tracks"]["t1aaaaaaa"]["rekordbox_check"]
    assert (check["match"], check["aligned"], check["undo"]["rendered"]) == ("shifted", True, True)
    assert np.array_equal(pcm(paths.root / check["undo"]["held"]), parked)  # the download, kept for the undo
    assert not (paths.root / PARKED).exists() and not (paths.tmp / "t1aaaaaaa").exists()
    assert r.path == NEW_NAME and "lined up" in r.note


@needs_ffmpeg
def test_new_track_for_an_mp3_shifts_by_rekordboxs_offset(tmp_path):
    """An MP3 whose rekordbox track sits d = 1105 samples later than ffmpeg's decode: the new file gets them in front,
    so the old track's cues fit (L − d with L = 0)."""
    from audio_helpers import pcm
    from discjockey.audio import write_tags
    paths = Paths(tmp_path, support=tmp_path / ".support")
    old = "Library/A/not_lossless/Artist - Song.mp3"
    (paths.root / old).parent.mkdir(parents=True)
    (paths.root / PARKED).parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures" / "clicks-lame.mp3", paths.root / old)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(paths.root / old), "-c:a", "pcm_s16be",
                    str(paths.root / PARKED)], check=True)  # the same edit, lossless
    write_tags(paths.root / PARKED, title="Song", artists=("Artist",), album="Album", isrc=None, label=None,
               cover=None, comment="Qobuz FLAC · verified lossless")
    state = empty_state()
    state["tracks"]["t1aaaaaaa"] = make_entry(path=old)
    parked = pcm(paths.root / PARKED)
    add(paths, state, EXACT, timing(1105))
    out = pcm(paths.root / NEW_NAME)
    assert np.all(out[:1105] == 0) and np.array_equal(out[1105:], parked)
    assert (paths.root / "Superseded/A/Artist - Song.mp3").exists()
    assert state["tracks"]["t1aaaaaaa"]["rekordbox_check"]["aligned"] is True
