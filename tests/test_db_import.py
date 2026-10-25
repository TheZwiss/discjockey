"""library.db for the import: import rows, own songs, watched folders, decisions, duplicates and the file journal
(plan library stage 4, group 1)."""
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from discjockey import db
from discjockey.library import StateError, empty_state
from discjockey.models import OwnFacts, PlannedMove, ScanResult, SeenFile

NOW = datetime(2026, 10, 25, 12, 0, 0)
LATER = datetime(2026, 10, 26, 9, 0, 0)
DRIVE = "/Volumes/Example/Music"
IN_LIBRARY = "Library/House/Example Artist - Kept.aiff"


def facts_of(present):
    def facts(path):
        return db.FileFacts(100, 1000, f"key-{path}") if path in present else None
    return facts


def entry(artist, title, path=None, **kw):
    e = dict.fromkeys(db.ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, folder="House", in_playlists=True, added="2026-10-01T10:00:00",
             rejected_sources=[], path=path, status="lossless" if path else "missing")
    if path:
        e.update(source="qobuz", source_id="123", source_format="flac 16/44.1", cutoff_hz=22000)
    e.update(kw)
    return e


def own(artist="Example Artist", title="Own Track", duration_ms=200000):
    return OwnFacts(artist, title, "Example Album", None, duration_ms, "mp3", "not_lossless")


class Lib:
    """A library.db with a Library/ song (sp1) and helpers for an import folder on a made-up drive."""

    def __init__(self, tmp_path):
        self.library = tmp_path / "music" / "Library"
        self.library.mkdir(parents=True)
        self.path = tmp_path / "library.db"
        self.present = {IN_LIBRARY}
        db.create(self.path, {**empty_state(), "tracks": {"sp1": entry("Example Artist", "Kept", IN_LIBRARY)}},
                  library=self.library, facts=facts_of(self.present), now=NOW)

    def conn(self):
        return db.connect(self.path)

    def folder(self, path=DRIVE):
        with self.conn() as conn:
            return db.add_watched_folder(conn, Path(path), NOW)

    def scan(self, result, now=NOW):
        with self.conn() as conn:
            return db.apply_scan(conn, result, now)

    def add_files(self, folder, *rels, key=None):
        """New files found in `folder` by a scan; returns their file ids."""
        self.scan(ScanResult(new=[SeenFile(folder, rel, 100, 1000, key or f"key-{folder}-{rel}") for rel in rels]))
        return [self.file_id(folder, rel) for rel in rels]

    def file_id(self, folder, rel):
        return self.rows("SELECT id FROM files WHERE folder = ? AND path = ?", folder, rel)[0][0]

    def rows(self, sql, *args):
        with self.conn() as conn:
            return conn.execute(sql, args).fetchall()

    def snap(self):
        with self.conn() as conn:
            return db.snapshot(conn, self.library)

    def save(self, state):
        with self.conn() as conn:
            return db.save(conn, state, library=self.library, facts=facts_of(self.present), now=LATER)

    def own_song(self, file_id, facts=None):
        with self.conn() as conn:
            return db.add_own_song(conn, file_id, facts or own())

    def generation(self):
        return int(self.rows("SELECT value FROM meta WHERE key = 'generation'")[0][0])


@pytest.fixture
def lib(tmp_path):
    return Lib(tmp_path)


# --- 1.4 import rows and own songs ---

def test_new_import_folder_rows_wait_and_library_rows_dont(lib):
    folder = lib.folder().id
    a, b = lib.add_files(folder, "A.mp3", "Sub/B.flac")
    lib.scan(ScanResult(new=[SeenFile(1, "House/New.aiff", 1, 1, "key-new")]))
    assert lib.rows("SELECT import_state FROM files WHERE path = 'House/New.aiff'") == [(None,)]
    with lib.conn() as conn:
        waiting = db.import_waiting(conn)
    assert [(r.file_id, r.path, r.folder, r.state) for r in waiting] == [
        (a, Path(DRIVE) / "A.mp3", folder, "new"), (b, Path(DRIVE) / "Sub/B.flac", folder, "new")]


def test_copies_in_an_import_folder_wait_too(lib):
    folder = lib.folder().id
    lib.scan(ScanResult(copies=[SeenFile(folder, "Copy.aiff", 1, 1, f"key-{IN_LIBRARY}")]))
    assert lib.rows("SELECT import_state, placed_by FROM files WHERE path = 'Copy.aiff'") == [("new", "import")]


def test_own_song_keys_increase_and_are_never_reused(lib):
    folder = lib.folder().id
    a, b, c = lib.add_files(folder, "A.mp3", "B.mp3", "C.mp3")
    assert lib.own_song(a) == "local:1"
    assert lib.own_song(b) == "local:2"
    lib.scan(ScanResult(gone=[b]), LATER)  # local:2 goes with its file
    assert lib.rows("SELECT key FROM songs WHERE key LIKE 'local:%' ORDER BY id") == [("local:1",)]
    assert lib.own_song(c) == "local:3"


def test_an_own_song_links_its_file_with_the_provisional_quality(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "A.mp3")
    before = lib.generation()
    key = lib.own_song(a)
    assert lib.generation() == before + 1
    assert lib.rows("SELECT status, source, source_format, import_state, placed_by FROM files WHERE id = ?", a) == [
        ("not_lossless", "manual", "mp3", "identified", "import")]
    state = lib.snap()
    e = state["tracks"][key]
    assert (e["artist"], e["title"], e["album"], e["duration_ms"], e["in_playlists"]) == (
        "Example Artist", "Own Track", "Example Album", 200000, False)
    assert (e["path"], e["import_state"], e["first_seen"], e["file_id"]) == (
        f"{DRIVE}/A.mp3", "identified", "2026-10-25T12:00:00", a)
    assert lib.save(state) == 0  # an own song round-trips


def test_a_row_with_a_song_is_left_alone(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "A.mp3")
    key = lib.own_song(a)
    before, generation = lib.rows("SELECT * FROM files WHERE id = ?", a), lib.generation()
    assert lib.own_song(a, own(title="Something Else")) == key
    assert lib.rows("SELECT * FROM files WHERE id = ?", a) == before and lib.generation() == generation
    with lib.conn() as conn, pytest.raises(ValueError):
        db.add_own_song(conn, 999, own())


def test_sound_and_unreadable_and_the_counts(lib):
    folder = lib.folder().id
    a, b, c, d = lib.add_files(folder, "A.mp3", "B.mp3", "C.mp3", "D.mp3")
    lib.own_song(a)
    lib.own_song(b)
    with lib.conn() as conn:
        db.set_sound(conn, a, "lossless", 22000, None)
        db.set_unreadable(conn, c, "the file is damaged")
        db.set_sound(conn, 999, "lossless", None, None)  # a row gone meanwhile: nothing
        counts = db.import_counts(conn)
        waiting = db.import_waiting(conn)
    assert lib.rows("SELECT status, cutoff_hz, import_state FROM files WHERE id = ?", a) == [("lossless", 22000, "done")]
    assert lib.rows("SELECT import_state, import_error FROM files WHERE id = ?", c) == [
        ("unreadable", "the file is damaged")]
    assert counts == {folder: db.ImportCounts(files=4, waiting=1, identified=1, unreadable=1)}
    assert [(r.file_id, r.state) for r in waiting] == [(c, "unreadable"), (d, "new")]


def test_the_sound_of_a_file_with_no_song_yet_is_refused(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "A.mp3")
    with lib.conn() as conn, pytest.raises(ValueError):
        db.set_sound(conn, a, "lossless", 22000, None)
    assert lib.rows("SELECT status, import_state FROM files WHERE id = ?", a) == [(None, "new")]


def test_offline_and_held_rows_arent_waiting(lib):
    folder = lib.folder().id
    other = lib.folder("/Volumes/Other/Music").id
    a, = lib.add_files(folder, "A.mp3")
    b, c = lib.add_files(other, "B.mp3", "C.mp3")
    lib.scan(ScanResult(offline=[folder], held=[c]))
    with lib.conn() as conn:
        assert [r.file_id for r in db.import_waiting(conn)] == [b]
        assert db.import_counts(conn)[folder].waiting == 1  # counted, not offered


# --- 1.5 watched folders ---

def test_a_folder_holding_import_folders_takes_them_over(lib):
    inner = lib.folder(f"{DRIVE}/Inner").id
    a, b = lib.add_files(inner, "A.mp3", "Deep/B.mp3")
    key = lib.own_song(a)
    before = lib.snap()["tracks"][key]
    added = lib.folder()
    assert added.merged == [f"{DRIVE}/Inner"]
    assert lib.rows("SELECT id, folder, path FROM files WHERE id IN (?, ?) ORDER BY id", a, b) == [
        (a, added.id, "Inner/A.mp3"), (b, added.id, "Inner/Deep/B.mp3")]
    assert lib.rows("SELECT id FROM watched_folders WHERE id = ?", inner) == []
    after = lib.snap()["tracks"][key]
    assert after == before  # the link, the absolute path and the import state stay


@pytest.mark.parametrize("where, reason", [
    (f"{DRIVE}/Sub", "watched"), (DRIVE, "already"), ("{library}/House", "music"), ("{music}", "music"),
    ("{music}/Other", "music"), ("{parent}", "holds_music"), ("/", "holds_music")])
def test_nested_folders_are_refused(lib, where, reason):
    lib.folder()
    path = where.format(library=lib.library, music=lib.library.parent, parent=lib.library.parent.parent)
    before = lib.rows("SELECT * FROM watched_folders")
    with lib.conn() as conn, pytest.raises(db.FolderRefused) as e:
        db.add_watched_folder(conn, Path(path), NOW)
    assert e.value.reason == reason
    assert lib.rows("SELECT * FROM watched_folders") == before


@pytest.mark.parametrize("where, reason", [
    (f"{DRIVE}/Sub/..", "already"), (f"{DRIVE}/Sub/../Sub/Deeper", "watched"), ("/VOLUMES/example/MUSIC", "already"),
    ("/Volumes/Example/MUSIC/Sub", "watched"), ("{library}/House/../..", "music"), ("{music_upper}/Other", "music"),
    ("{parent_upper}", "holds_music")])
def test_nesting_is_judged_on_the_resolved_path_ignoring_case(lib, where, reason):
    lib.folder()
    music = str(lib.library.parent)
    path = where.format(library=lib.library, music_upper=music.upper(), parent_upper=str(lib.library.parent.parent).upper())
    with lib.conn() as conn, pytest.raises(db.FolderRefused) as e:
        db.add_watched_folder(conn, Path(path), NOW)
    assert e.value.reason == reason


def test_a_folder_is_stored_resolved(lib, tmp_path):
    real = tmp_path / "Real Music"
    real.mkdir()
    (tmp_path / "Link").symlink_to(real)
    lib.folder(f"{DRIVE}/Sub/../Other")
    lib.folder(str(tmp_path / "Link"))
    assert lib.rows("SELECT path FROM watched_folders WHERE kind = 'import' ORDER BY id") == [
        (f"{DRIVE}/Other",), (str(real.resolve()),)]
    with lib.conn() as conn, pytest.raises(db.FolderRefused) as e:
        db.add_watched_folder(conn, real / "Inside", NOW)  # inside the folder the link names
    assert e.value.reason == "watched"


def test_a_relative_folder_is_refused(lib):
    with lib.conn() as conn, pytest.raises(ValueError):
        db.add_watched_folder(conn, Path("Music"), NOW)


def removal_setup(lib):
    """An import folder with: a playlist song whose only file is there (sp2), a playlist song gone from the
    playlists with its file there (sp3), an own song; and a Library song (sp1)."""
    folder = lib.folder().id
    a, b, c = lib.add_files(folder, "Wanted.aiff", "Old.aiff", "Own.mp3")
    lib.present.update({f"{DRIVE}/Wanted.aiff", f"{DRIVE}/Old.aiff"})
    state = lib.snap()
    state["tracks"]["sp2"] = entry("Example Artist", "Wanted", f"{DRIVE}/Wanted.aiff")
    state["tracks"]["sp3"] = entry("Example Artist", "Old", f"{DRIVE}/Old.aiff", in_playlists=False)
    lib.save(state)
    key = lib.own_song(c)
    return folder, (a, b, c), key


def test_removal_counts_the_playlist_songs_that_lose_their_only_file(lib):
    folder, _, _ = removal_setup(lib)
    with lib.conn() as conn:
        assert db.removal_counts(conn, folder) == db.RemovalCounts(files=3, redownload=1)
        with pytest.raises(ValueError):
            db.removal_counts(conn, 1)  # the Library folder


def test_removing_a_folder_drops_its_rows_and_own_songs_and_keeps_playlist_songs(lib):
    folder, (a, b, c), key = removal_setup(lib)
    other = lib.folder("/Volumes/Other/Music").id
    (d,) = lib.add_files(other, "Elsewhere.mp3")
    elsewhere = lib.own_song(d)
    sp1 = lib.snap()["tracks"]["sp1"]["file_id"]
    with lib.conn() as conn:
        db.set_decision(conn, "same_song", "sp9", key, "not_same", NOW)  # its own song goes
        db.set_decision(conn, "same_song", "sp8", elsewhere, "not_same", NOW)
        db.set_decision(conn, "keep_both", db.group_id([sp1, a]), "", "keep", NOW)  # one of its files goes
        db.set_decision(conn, "keep_both", db.group_id([sp1, d]), "", "keep", NOW)
        before = lib.generation()
        assert db.remove_watched_folder(conn, folder, date(2026, 10, 26)) == db.RemovalCounts(3, 1)
        assert db.decisions(conn) == {"same_song": [["sp8", elsewhere, "not_same"]],
                                      "keep_both": [db.group_id([sp1, d])]}
    assert lib.generation() == before + 1
    assert lib.rows("SELECT key, file_gone FROM songs ORDER BY id") == [
        ("sp1", None), ("sp2", "2026-10-26"), ("sp3", "2026-10-26"), (elsewhere, None)]
    assert lib.rows("SELECT COUNT(*) FROM files WHERE folder = ?", folder) == [(0,)]
    assert lib.rows("SELECT id FROM watched_folders WHERE id = ?", folder) == []
    tracks = lib.snap()["tracks"]
    assert tracks["sp2"]["path"] is None and tracks["sp1"]["path"] == IN_LIBRARY


def test_the_library_folder_is_never_removed(lib):
    with lib.conn() as conn:
        for folder in (1, 42):
            with pytest.raises(ValueError):
                db.remove_watched_folder(conn, folder, date(2026, 10, 26))
    assert lib.rows("SELECT id FROM watched_folders") == [(1,)]


# --- 1.6 decisions and duplicates ---

def test_decisions_are_validated_replaced_and_in_the_snapshot(lib):
    with lib.conn() as conn:
        db.set_decision(conn, "same_song", "sp2", "local:1", "same", NOW)
        db.set_decision(conn, "same_song", "sp2", "local:1", "not_same", LATER)
        db.set_decision(conn, "keep_both", "dup:3-4", "", "keep", NOW)
        for bad in (("same_song", "sp2", "local:1", "keep"), ("keep_both", "dup:3-4", "x", "keep"),
                    ("keep_both", "sp2", "", "keep"), ("other", "a", "b", "same")):
            with pytest.raises(ValueError):
                db.set_decision(conn, *bad, NOW)
    assert lib.snap()["decisions"] == {"same_song": [["sp2", "local:1", "not_same"]], "keep_both": ["dup:3-4"]}
    assert lib.rows("SELECT at FROM decisions WHERE kind = 'same_song'") == [("2026-10-26T09:00:00",)]


def test_three_files_with_one_key_are_one_group_until_decided(lib):
    folder = lib.folder().id
    ids = lib.add_files(folder, "A.mp3", "B.mp3", "C.mp3", key="key-same")
    lib.add_files(folder, "Other.mp3")
    with lib.conn() as conn:
        groups = db.duplicate_groups(conn)
        assert groups == [db.DuplicateGroup("dup:" + "-".join(map(str, ids)), "same_audio", tuple(ids))]
        db.set_decision(conn, "keep_both", groups[0].id, "", "keep", NOW)
        assert db.duplicate_groups(conn) == []
    lib.scan(ScanResult(copies=[SeenFile(folder, "D.mp3", 100, 1000, "key-same")]))
    with lib.conn() as conn:
        (group,) = db.duplicate_groups(conn)  # a new copy: another group, asked again
    assert group.file_ids == (*ids, lib.file_id(folder, "D.mp3"))


def test_offline_held_and_ambiguous_files_are_left_out(lib):
    folder = lib.folder().id
    other = lib.folder("/Volumes/Other/Music").id
    a, b = lib.add_files(folder, "A.mp3", "B.mp3", key="key-one")
    (c,) = lib.add_files(other, "C.mp3", key="key-one")
    lib.add_files(folder, "D.mp3", "E.mp3", key="key-two")
    d, e = lib.file_id(folder, "D.mp3"), lib.file_id(folder, "E.mp3")
    lib.scan(ScanResult(offline=[other], held=[a], ambiguous=[(d, [f"{DRIVE}/X.mp3"])]))
    with lib.conn() as conn:
        assert db.duplicate_groups(conn) == []
    lib.scan(ScanResult(ambiguous=[(d, [f"{DRIVE}/X.mp3"])]))  # back online, nothing held
    with lib.conn() as conn:
        assert [g.file_ids for g in db.duplicate_groups(conn)] == [(a, b, c)]


def test_group_files_show_each_file_of_a_group(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "A.aiff", key=f"key-{IN_LIBRARY}")
    key = lib.own_song(a)
    sp1 = lib.snap()["tracks"]["sp1"]["file_id"]
    with lib.conn() as conn:
        (group,) = db.duplicate_groups(conn)
        files = db.group_files(conn, group.id)
        with pytest.raises(ValueError):
            db.group_files(conn, "dup:x")
        assert [f.file_id for f in db.group_files(conn, f"dup:{a}-999")] == [a]
    assert files == [
        db.DupFile(sp1, "sp1", IN_LIBRARY, "lossless", 22000, "flac 16/44.1", True, True),
        db.DupFile(a, key, f"{DRIVE}/A.aiff", "not_lossless", None, "mp3", True, False)]


# --- 1.7 scan and save ---

def test_a_gone_own_song_is_deleted_and_a_gone_playlist_song_downloads_again(lib):
    folder, (a, b, c), key = removal_setup(lib)
    with lib.conn() as conn:
        db.set_decision(conn, "same_song", "sp9", key, "not_same", NOW)
    lib.scan(ScanResult(gone=[a, c]), LATER)
    assert lib.rows("SELECT key, file_gone FROM songs ORDER BY id") == [
        ("sp1", None), ("sp2", "2026-10-26"), ("sp3", None)]
    assert lib.rows("SELECT * FROM decisions") == []


def test_a_merge_through_save_keeps_placed_by_import(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "Track.aiff")
    path = f"{DRIVE}/Track.aiff"
    lib.present.add(path)
    key = lib.own_song(a)
    with lib.conn() as conn:
        db.set_sound(conn, a, "lossless", 22000, None)
    state = lib.snap()
    state["tracks"]["sp2"] = entry("Example Artist", "Track")
    lib.save(state)
    state = lib.snap()
    o = state["tracks"].pop(key)  # rule 2's merge: the playlist song takes the own song's file
    state["tracks"]["sp2"].update({k: o[k] for k in db.FILE_FIELDS})
    lib.save(state)
    assert lib.rows("SELECT s.key, f.placed_by, f.import_state, f.status FROM files f JOIN songs s ON s.id = f.song "
                    "WHERE f.id = ?", a) == [("sp2", "import", "done", "lossless")]
    assert lib.rows("SELECT key FROM songs WHERE key = ?", key) == []


def test_a_save_drops_the_answers_naming_what_it_removed(lib):
    folder = lib.folder().id
    a, b = lib.add_files(folder, "Track.aiff", "Copy.aiff")
    path = f"{DRIVE}/Track.aiff"
    lib.present.add(path)
    key, other = lib.own_song(a), lib.own_song(b)
    state = lib.snap()
    state["tracks"]["sp2"] = entry("Example Artist", "Track")
    lib.save(state)
    with lib.conn() as conn:
        db.set_decision(conn, "same_song", "sp2", key, "same", NOW)
        db.set_decision(conn, "same_song", "sp3", other, "not_same", NOW)
        db.set_decision(conn, "keep_both", db.group_id([a, b]), "", "keep", NOW)
    state = lib.snap()
    o = state["tracks"].pop(key)  # the merge: the own song goes
    state["tracks"]["sp2"].update({k: o[k] for k in db.FILE_FIELDS})
    state["tracks"].pop(other)  # an own song whose file is gone from disk: its row goes too
    lib.save(state)
    assert lib.rows("SELECT id FROM files WHERE id = ?", b) == []
    assert lib.snap()["decisions"] == {"same_song": [], "keep_both": []}


# --- 1.8 the file journal ---

def library_moves(lib, n):
    """`n` Library songs with files, and a tidy batch planning one move per file (House -> Techno)."""
    state = lib.snap()
    for i in range(n):
        p = f"Library/House/Example Artist - Move {i}.aiff"
        lib.present.add(p)
        state["tracks"][f"m{i}"] = entry("Example Artist", f"Move {i}", p)
    lib.save(state)
    tracks = lib.snap()["tracks"]
    moves = [PlannedMove("file", tracks[f"m{i}"]["file_id"], f"Example Artist - Move {i}",
                         tracks[f"m{i}"]["path"], tracks[f"m{i}"]["path"].replace("House", "Techno"),
                         None, "app", "user") for i in range(n)]
    with lib.conn() as conn:
        batch = db.start_batch(conn, started_by="tidy", about=None, undoes=None, moves=moves, now=NOW)
        return [m.id for m in db.batch_moves(conn, batch)]


def test_pending_ops_get_an_id_and_are_dropped_by_it(lib):
    op = {"do": "supersede", "ref": 1}
    with lib.conn() as conn:
        op_id = db.add_pending(conn, op)
        assert op["op_id"] == op_id and len(op_id) == 32
        assert db.add_pending(conn, {"do": "supersede", "ref": 2, "op_id": "fixed"}) == "fixed"
        assert lib.snap()["pending"] == [op, {"do": "supersede", "ref": 2, "op_id": "fixed"}]
        db.drop_pending(conn, op_id)
    assert lib.snap()["pending"] == [{"do": "supersede", "ref": 2, "op_id": "fixed"}]
    assert lib.generation() == 3


def test_a_tidy_move_finishes_exactly_as_finish_move(lib):
    first, second = library_moves(lib, 2)
    with lib.conn() as conn:
        generation = lib.generation()
        db.finish_move(conn, first)
        assert lib.generation() == generation + 1
        db.finish_move(conn, first)  # done already: nothing written
        assert lib.generation() == generation + 1
        op = {"do": "tidy_move", "ref": second}
        db.add_pending(conn, op)
        db.finish_file_op(conn, op)
        rows = {m.id: m for m in db.batch_moves(conn, db.open_batches(conn)[0])}
    assert rows[first].state == rows[second].state == "done"
    assert lib.rows("SELECT path, placed_by FROM files WHERE path LIKE 'Techno/%' ORDER BY path") == [
        ("Techno/Example Artist - Move 0.aiff", "user"), ("Techno/Example Artist - Move 1.aiff", "user")]
    assert lib.snap()["pending"] == []


def test_a_failing_file_op_leaves_pending_and_rows_as_they_were(lib):
    (move,) = library_moves(lib, 1)
    state = lib.snap()  # another song's linked file sits where the move goes
    target = "Library/Techno/Example Artist - Move 0.aiff"
    lib.present.add(target)
    state["tracks"]["sp7"] = entry("Example Artist", "In The Way", target)
    lib.save(state)
    before = {t: lib.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in ("files", "songs", "moves", "pending")}
    op = {"do": "tidy_move", "ref": move}
    with lib.conn() as conn:
        db.add_pending(conn, op)
        pending = lib.rows("SELECT * FROM pending")
        generation = lib.generation()
        with pytest.raises(sqlite3.IntegrityError):
            db.finish_file_op(conn, op)
        with pytest.raises(ValueError):
            db.finish_file_op(conn, {"do": "rename", "ref": move, "op_id": op["op_id"]})
    assert lib.rows("SELECT * FROM pending") == pending and lib.generation() == generation
    assert {t: lib.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in ("files", "songs", "moves")} == {
        t: before[t] for t in ("files", "songs", "moves")}


def test_supersede_without_heir_drops_the_row_and_an_own_song_left_with_none(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "A.mp3")
    key = lib.own_song(a)
    op = {"do": "supersede", "ref": a, "heir": None}
    with lib.conn() as conn:
        db.add_pending(conn, op)
        db.finish_file_op(conn, op)
    assert lib.rows("SELECT id FROM files WHERE id = ?", a) == []
    assert lib.rows("SELECT key FROM songs WHERE key = ?", key) == []
    assert lib.snap()["pending"] == []


def test_supersede_with_an_heir_hands_the_playlist_song_to_the_other_file(lib):
    folder = lib.folder().id
    (a,) = lib.add_files(folder, "Better.aiff", key=f"key-{IN_LIBRARY}")
    key = lib.own_song(a)
    sp1 = lib.snap()["tracks"]["sp1"]["file_id"]
    bad = {"do": "supersede", "ref": sp1, "heir": sp1 + 1000}
    op = {"do": "supersede", "ref": sp1, "heir": a}
    with lib.conn() as conn:
        db.add_pending(conn, bad)
        with pytest.raises(ValueError):
            db.finish_file_op(conn, bad)
        db.drop_pending(conn, bad["op_id"])
        db.add_pending(conn, op)
        db.finish_file_op(conn, op)
    tracks = lib.snap()["tracks"]
    assert key not in tracks
    assert (tracks["sp1"]["path"], tracks["sp1"]["file_id"], tracks["sp1"]["placed_by"]) == (
        f"{DRIVE}/Better.aiff", a, "import")
    assert lib.rows("SELECT id FROM files WHERE id = ?", sp1) == []


def test_a_snapshot_from_before_a_journal_write_isnt_saved(lib):
    state = lib.snap()
    with lib.conn() as conn:
        db.add_pending(conn, {"do": "supersede", "ref": 1})
    state["never"] = {"sp9": {"artist": "Z"}}
    with pytest.raises(StateError):
        lib.save(state)


def test_finish_move_keeps_a_current_writer_saving_and_a_stale_one_stale(lib):
    first, second = library_moves(lib, 2)
    current, stale = lib.snap(), lib.snap()
    with lib.conn() as conn:
        db.finish_move(conn, first, state=current)
        assert current["generation"] == lib.generation()
        db.finish_move(conn, second, state=stale)  # stale since the first move
    assert stale["generation"] == lib.generation() - 2
    with pytest.raises(StateError):
        lib.save(stale)
