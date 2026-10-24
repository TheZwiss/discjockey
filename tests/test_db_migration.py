"""state.json -> library.db (spec library-and-sources §5.3, §13 "db / migration"; plan library stage 1, task 1.4)."""
import hashlib
import json
from datetime import datetime

import pytest

from discjockey import db
from discjockey.events import Message
from discjockey.library import Paths, StateError, _load_v1, write_json_atomic
from test_db import entry, fake_facts, v1_state, without_read_only

NOW = datetime(2026, 10, 23, 12, 0, 0)
ONE = "Library/House/A - One.mp3"


class Crash(BaseException):
    """A crash (power cut, kill): no cleanup code runs."""


def migration_state():
    """v1_state plus a pending plain rename and a pending swap."""
    state = v1_state()
    state["pending"] = [
        {"track_id": "sp3", "renames": [["Library/Techno/old.aiff", "Library/Techno/C - Thrée.aiff"]],
         "entry": None},
        {"kind": "swap", "track_id": "sp1", "target": ONE, "staged": ".discjockey/.tmp/x.aiff",
         "backup": "Superseded/House/A - One.mp3", "parked": None, "backed_up": False},
    ]
    return state


@pytest.fixture
def lib(tmp_path):
    paths = Paths(tmp_path / "music", support=tmp_path / ".support")
    paths.library.mkdir(parents=True)
    paths.data.mkdir()
    write_json_atomic(paths.state_file, migration_state(), indent=2, ensure_ascii=False, sort_keys=True)
    return paths


def run(paths, *, recover=lambda state: None, events=None):
    db.migrate(paths, facts=fake_facts({ONE}), now=NOW, emit=(events if events is not None else []).append,
               recover=recover)


def snapshot(paths):
    with db.connect(db.db_file(paths)) as conn:
        db.check(conn)
        return db.snapshot(conn, paths.library)


def assert_migrated(paths, original: bytes):
    state = json.loads(original)
    snap = snapshot(paths)
    assert without_read_only(snap["tracks"]) == {k: {**e, "file_gone": None} for k, e in state["tracks"].items()}
    for key in ("pending", "never", "qobuz_usage", "youtube_usage"):
        assert snap[key] == state[key]
    assert json.loads(paths.state_file.read_text()) == {"version": 2, "moved_to": "library.db"}
    assert (paths.data / "state.v1.json").read_bytes() == original
    assert not (paths.data / "library.db.tmp").exists()


def test_migration_builds_the_expected_rows(lib):
    original = lib.state_file.read_bytes()
    seen, events = [], []
    run(lib, recover=lambda state: seen.append(state["version"]), events=events)
    assert seen == [1]
    assert events == [Message("info", "Updating Discjockey's records of your library (only this once; it can take "
                                      "a minute)...")]
    assert_migrated(lib, original)
    with db.connect(db.db_file(lib)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'migrated_from'").fetchone()[0] == \
            hashlib.sha256(original).hexdigest()
        rows = conn.execute("SELECT path, size, mtime_ns, content_key FROM files ORDER BY id").fetchall()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert rows == [("House/A - One.mp3", len(ONE), 1000 + len(ONE), f"key-{ONE}"),
                    ("Techno/C - Thrée.aiff", None, None, None)]  # listed in state.json, not on disk


def test_recovery_runs_first_and_the_hash_is_of_the_recovered_state_json(lib):
    def recover(state):
        state["pending"] = []
        state["tracks"]["sp2"]["last_attempt"] = "2026-10-23"
        write_json_atomic(lib.state_file, state, indent=2, ensure_ascii=False, sort_keys=True)

    run(lib, recover=recover)
    recovered = (lib.data / "state.v1.json").read_bytes()
    assert_migrated(lib, recovered)
    assert snapshot(lib)["pending"] == []
    with db.connect(db.db_file(lib)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'migrated_from'").fetchone()[0] == \
            hashlib.sha256(recovered).hexdigest()


def test_the_stub_is_refused_by_the_v1_reader_with_the_old_words(lib):
    run(lib)
    assert json.loads(lib.state_file.read_text()) == {"version": 2, "moved_to": "library.db"}
    with pytest.raises(StateError) as e:
        _load_v1(lib.state_file)
    assert str(e.value) == "state.json has version 2, this Discjockey only knows version 1. Nothing was changed."


def test_a_finished_migration_does_nothing_the_next_time(lib):
    run(lib)
    before = snapshot(lib), lib.state_file.read_bytes(), (lib.data / "state.v1.json").read_bytes()
    events = []
    run(lib, recover=lambda state: pytest.fail("recovered again"), events=events)
    assert events == []
    assert (snapshot(lib), lib.state_file.read_bytes(), (lib.data / "state.v1.json").read_bytes()) == before


STEPS = ["_read_v1", "recover", "_build", "_place", "_backup", "_write_stub"]


@pytest.mark.parametrize("step", STEPS)
def test_a_crash_after_any_step_leaves_a_library_the_next_migration_finishes(lib, monkeypatch, step):
    original = lib.state_file.read_bytes()

    def crash_after(fn):
        def wrapped(*a, **k):
            fn(*a, **k)
            raise Crash
        return wrapped

    recover = lambda state: None  # noqa: E731
    if step == "recover":
        recover = crash_after(recover)
    else:
        monkeypatch.setattr(db, step, crash_after(getattr(db, step)))
    with pytest.raises(Crash):
        run(lib, recover=recover)
    assert lib.state_file.exists()  # never missing, also between the backup and the stub
    if STEPS.index(step) < STEPS.index("_place"):
        assert lib.state_file.read_bytes() == original
        assert not db.db_file(lib).exists()
    monkeypatch.undo()
    run(lib)
    assert_migrated(lib, original)


def test_a_failure_before_placing_removes_the_temp_file_and_says_so(lib, monkeypatch):
    original = lib.state_file.read_bytes()

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(db, "_place", full)
    with pytest.raises(StateError) as e:
        run(lib)
    assert str(e.value) == ("Discjockey couldn't update its records of your library (no space left on device). "
                            "Nothing was changed; it tries again next time.")
    assert lib.state_file.read_bytes() == original
    assert sorted(p.name for p in lib.data.iterdir()) == ["state.json"]


def test_a_state_json_changed_after_placing_is_migrated_again(lib, monkeypatch):
    def crash(paths):
        raise Crash

    monkeypatch.setattr(db, "_backup", crash)
    with pytest.raises(Crash):
        run(lib)
    monkeypatch.undo()
    # an older Discjockey ran in between and added a song to state.json
    state = json.loads(lib.state_file.read_text())
    state["tracks"]["sp4"] = entry("D", "Four")
    write_json_atomic(lib.state_file, state, indent=2, ensure_ascii=False, sort_keys=True)
    changed = lib.state_file.read_bytes()
    run(lib)
    assert (lib.data / "library.db.discarded").exists()
    assert_migrated(lib, changed)
    assert "sp4" in snapshot(lib)["tracks"]


def test_a_new_library_gets_an_empty_database_and_the_stub(lib):
    lib.state_file.unlink()
    run(lib)
    assert snapshot(lib)["tracks"] == {}
    assert json.loads(lib.state_file.read_text()) == {"version": 2, "moved_to": "library.db"}
    assert not (lib.data / "state.v1.json").exists()


def write_state(paths, tracks):
    state = {"version": 1, "tracks": tracks, "pending": [], "never": {}, "qobuz_usage": {"days": {}, "signals": []}}
    write_json_atomic(paths.state_file, state, indent=2, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize("named_first", [True, False])
def test_a_file_two_entries_share_stays_with_the_one_it_is_named_after(lib, named_first):
    shared = "Library/House/B - Two.aiff"
    named = entry("B", "Two", shared, added="2026-10-05T10:00:00")
    other = entry("X", "Other", shared, added="2026-10-01T10:00:00", source_kbps=320)
    write_state(lib, {"a": named, "b": other} if named_first else {"a": other, "b": named})
    events = []
    run(lib, events=events)
    tracks = snapshot(lib)["tracks"]
    keep, lose = ("a", "b") if named_first else ("b", "a")
    assert tracks[keep]["path"] == shared
    assert {k: tracks[lose][k] for k in ("path", "status", "source", "source_id", "source_kbps")} == {
        "path": None, "status": "missing", "source": None, "source_id": None, "source_kbps": None}
    assert Message("warning", "Two songs pointed at the same file, Library/House/B - Two.aiff: it stays with B - Two, "
                              "and X - Other will be downloaded again.") in events


def test_without_a_name_match_the_earlier_added_entry_keeps_the_file(lib):
    shared = "Library/House/Neither.aiff"
    write_state(lib, {"a": entry("A", "One", shared, added="2026-10-09T10:00:00"),
                      "b": entry("B", "Two", shared, added="2026-10-01T10:00:00")})
    run(lib)
    tracks = snapshot(lib)["tracks"]
    assert (tracks["a"]["path"], tracks["b"]["path"]) == (None, shared)


def test_an_alias_two_songs_share_stays_with_the_first_and_says_so(lib):
    write_state(lib, {"a": entry("A", "One", aliases=["x"]), "b": entry("B", "Two", aliases=["x"])})
    events = []
    run(lib, events=events)
    tracks = snapshot(lib)["tracks"]
    assert (tracks["a"]["aliases"], tracks["b"]["aliases"]) == (["x"], [])
    assert Message("warning", "B - Two and A - One share a Spotify link; it stays with A - One.") in events


MISSING_WORDS = ("Discjockey's records (library.db) are missing from the .discjockey folder. Nothing was changed. "
                 "Put the file back, for example from Time Machine, and open Discjockey again.")


@pytest.mark.parametrize("backup", [True, False])
def test_a_missing_database_is_never_rebuilt(lib, backup):
    """Plan stage 1, 3.1: no automatic restore (the backup doesn't know what Discjockey did since: rebuilding from it
    could download or misplace files)."""
    run(lib)
    db.db_file(lib).unlink()
    old = lib.data / "state.v1.json"
    if not backup:
        old.unlink()
    before = old.read_bytes() if backup else None
    stub = lib.state_file.read_bytes()
    with pytest.raises(StateError) as e:
        run(lib, recover=lambda state: pytest.fail("nothing is recovered"))
    assert str(e.value) == MISSING_WORDS
    assert not db.db_file(lib).exists() and lib.state_file.read_bytes() == stub
    assert (old.read_bytes() if backup else old.exists()) == (before if backup else False)


def test_opening_runs_the_version_check_and_follows_a_moved_music_folder(tmp_path, lib, monkeypatch):
    run(lib)
    moved = Paths(tmp_path / "moved", support=lib.support)
    lib.root.rename(moved.root)
    run(moved)
    with db.connect(db.db_file(moved)) as conn:
        assert conn.execute("SELECT path FROM watched_folders").fetchone()[0] == moved.library.as_posix()
        conn.execute("UPDATE meta SET value = '9' WHERE key = 'schema_version'")
    with pytest.raises(StateError, match="newer Discjockey"):
        run(moved)


def test_a_state_json_of_another_version_keeps_its_message(lib):
    lib.state_file.write_text(json.dumps({"version": 3, "tracks": {}}))
    with pytest.raises(StateError) as e:
        run(lib)
    assert str(e.value) == "state.json has version 3, this Discjockey only knows version 1. Nothing was changed."
    assert not db.db_file(lib).exists()
