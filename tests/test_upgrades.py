from datetime import datetime

import pytest

from discjockey import upgrades
from discjockey.align import Alignment
from discjockey import library
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
    assert load_state(paths.state_file) == state
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
    assert load_state(paths.state_file) == state


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
    assert e["rekordbox_check"] == {"reason": "added_as_new", "since": "2026-10-16"}
    assert state["pending"] == [] and load_state(paths.state_file) == state
    assert (r.section, r.path, r.status) == ("added_new", new, "lossless")


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
    assert load_state(paths.state_file)["tracks"]["t1aaaaaaa"]["upgrade"] is None


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
        save_state(paths_.state_file, state_)
        for src, dst in renames[:renames_done]:
            library.safe_rename(paths_.root, src, dst)
        raise KeyboardInterrupt

    monkeypatch.setattr(upgrades, "run_op", power_off)
    with pytest.raises(KeyboardInterrupt):
        upgrades.add_new(paths, state, "t1aaaaaaa", up(state))
    state = load_state(paths.state_file)
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
