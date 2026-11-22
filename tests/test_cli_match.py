"""`rekordbox match` and `library superseded` through the command line (issue 39 phase 3, V3.3b): a rekordbox library
holding a track of each kind, `--in` narrowing, no library, a writer holding `rekordbox.lock`, paging. The kinds
themselves are pinned on plain inputs in tests/test_rekordbox_match.py."""
import json
import shutil
from datetime import datetime

import pytest
from hub_helpers import LOSSLESS, LOSSY, choose_music, cmd, make_root
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import db, library, rekordbox, words
from discjockey.rekordbox import lock as rb_lock
from discjockey.rekordbox import master

HERE = "Library/Hard_Bounce"
OTHER = "Library/Other"


def data_of(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def put(root, rel, content=b"audio"):
    """A file at `rel` in the music folder."""
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(content)
    return str(file)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


@pytest.fixture
def elsewhere(tmp_path_factory):
    """A folder that is not in the music folder: where the DJ keeps files of their own."""
    return tmp_path_factory.mktemp("own")


def with_tracks(lib, tmp_path, monkeypatch, elsewhere):
    """A rekordbox library with a track of each kind (the hub fixture's song t1 is held and matched, t2 is not held).
    Superseded/Hard_Bounce holds two files and rekordbox points at one of them. Returns the paths by name."""
    root = lib.root
    mine = put(elsewhere, "own.mp3")
    held = {
        "matched": str(root / LOSSLESS),
        "stray": put(root, f"{HERE}/Stray.aiff"),
        "gone": str(root / HERE / "Gone.aiff"),
        "superseded": put(root, "Superseded/Hard_Bounce/Old.mp3"),
        "outside": mine,
        "other gone": str(root / OTHER / "Gone2.aiff"),
        "other superseded": put(root, "Superseded/Other/Old2.mp3"),
    }
    put(root, "Superseded/Hard_Bounce/Spare.mp3", b"spare file")
    put(root, "Superseded/.hidden.mp3")
    rows = [{"ID": str(i + 1), "path": p, "artist": f"Artist {name}", "Title": f"Title {name}"}
            for i, (name, p) in enumerate(held.items())]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", rows).parent))
    return held


def listed(env):
    return {(e["kind"], e["rel_path"] or e["path"]) for e in env["data"]["entries"]}


def test_match_lists_each_kind_and_counts_the_rest(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    code, env = data_of(["rekordbox", "match"], capsys)
    data = env["data"]
    assert code == 0 and env["outcome"] == "ok"
    assert data["counts"] == {"matched": 1, "missing": 2, "superseded": 2, "away": 0, "not_in_library": 1,
                              "not_in_rekordbox": 1, "outside": 1}
    assert [e["kind"] for e in data["entries"]] == ["missing", "missing", "superseded", "superseded", "not_in_library",
                                                    "not_in_rekordbox"]
    assert listed(env) == {("missing", f"{HERE}/Gone.aiff"), ("missing", f"{OTHER}/Gone2.aiff"),
                           ("superseded", "Superseded/Hard_Bounce/Old.mp3"), ("superseded", "Superseded/Other/Old2.mp3"),
                           ("not_in_library", f"{HERE}/Stray.aiff"), ("not_in_rekordbox", LOSSY)}
    first = data["entries"][0]
    assert (first["kind_text"], first["artist"], first["title"]) == (words.MATCH_KINDS["missing"], "Artist gone",
                                                                    "Title gone") and first["rekordbox_id"]
    lacking = data["entries"][-1]  # a file of the library: the library's artist and title, no rekordbox id, its song
    assert (lacking["track_id"], lacking["rekordbox_id"], lacking["artist"], lacking["title"]) == (
        "t2", None, "Armin Hermann", "Get Naughty") and lacking["path"] == str(lib.root / LOSSY)
    assert data["rekordbox"] == {"state": "ready", "state_text": words.REKORDBOX_STATE["ready"], "writing": False}


def test_match_says_in_words_what_it_found(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    _, env = data_of(["rekordbox", "match"], capsys)
    assert env["data"]["text"] == "5 rekordbox tracks need a look, 1 of your files is not in rekordbox."
    assert cli.main(["rekordbox", "match"]) == 0
    out = capsys.readouterr().out
    assert words.MATCH_KINDS["superseded"] in out and "Stray.aiff" in out


def test_match_when_everything_matches(lib, tmp_path, monkeypatch, capsys):
    rows = [{"path": str(lib.root / LOSSLESS)}, {"path": str(lib.root / LOSSY)}]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", rows).parent))
    code, env = data_of(["rekordbox", "match"], capsys)
    assert code == 0 and env["data"]["entries"] == [] and env["data"]["counts"]["matched"] == 2
    assert env["data"]["text"] == words.MATCH_ALL_GOOD


def test_match_in_a_collection_narrows_both_sides(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    code, env = data_of(["rekordbox", "match", "--in", "playlist:Hard_Bounce"], capsys)
    assert code == 0
    assert env["data"]["counts"] == {"matched": 1, "missing": 1, "superseded": 1, "away": 0, "not_in_library": 1,
                                     "not_in_rekordbox": 1, "outside": 0}  # Other/'s two tracks and the outside file are left out
    assert {e["rel_path"] for e in env["data"]["entries"]} == {
        f"{HERE}/Gone.aiff", "Superseded/Hard_Bounce/Old.mp3", f"{HERE}/Stray.aiff", LOSSY}
    code, env = data_of(["rekordbox", "match", "--in", "playlist:Powertrance"], capsys)  # no songs: nothing to compare
    assert code == 0 and env["data"]["entries"] == [] and sum(env["data"]["counts"].values()) == 0
    code, env = data_of(["rekordbox", "match", "--in", "folder:Library/Hard_Bounce"], capsys)
    assert code == 0 and env["data"]["counts"]["missing"] == 1


def test_match_names_a_drive_that_is_away_and_a_folder_nothing_knows(lib, tmp_path, monkeypatch, elsewhere, capsys):
    crate = elsewhere / "Crate"
    crate.mkdir()
    song = crate / "Crate Song.mp3"
    song.write_bytes(b"audio")
    with db.connect(lib.db_file) as conn:
        db.add_watched_folder(conn, crate, datetime(2026, 11, 1))
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", [{"path": str(song)}]).parent))
    _, here = data_of(["rekordbox", "match"], capsys)
    assert [e["kind"] for e in here["data"]["entries"]] == ["not_in_library", "not_in_rekordbox", "not_in_rekordbox"]
    shutil.rmtree(crate)  # the folder is gone (a drive that is not connected looks the same): its files are not "missing"
    _, away = data_of(["rekordbox", "match"], capsys)
    assert away["data"]["counts"]["away"] == 1 and away["data"]["counts"]["missing"] == 0
    assert [e["kind"] for e in away["data"]["entries"] if e["rekordbox_id"]] == ["away"]
    assert away["data"]["entries"][0]["kind_text"] == words.MATCH_KINDS["away"]


def test_match_pages_through_the_envelope(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    _, env = data_of(["rekordbox", "match", "--limit", "4"], capsys)
    assert len(env["data"]["entries"]) == 4
    assert env["page"] == {"list": "entries", "offset": 0, "limit": 4, "total": 6, "next_offset": 4}
    _, env = data_of(["rekordbox", "match", "--limit", "4", "--offset", "4"], capsys)
    assert [e["kind"] for e in env["data"]["entries"]] == ["not_in_library", "not_in_rekordbox"]
    assert env["page"]["next_offset"] is None


def test_match_without_a_rekordbox_library_has_nothing_to_compare(lib, tmp_path, monkeypatch, capsys):
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))
    code, env = data_of(["rekordbox", "match"], capsys)
    data = env["data"]
    assert code == 0 and data["entries"] == [] and sum(data["counts"].values()) == 0  # not every song as "not in rekordbox"
    assert data["rekordbox"]["state"] == "none" and data["text"] == words.MATCH_NO_REKORDBOX
    assert data["rekordbox"]["state_text"] == words.REKORDBOX_STATE["none"]


def test_match_with_an_unreadable_library_says_its_problem(lib, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", [], version="9999").parent))
    code, env = data_of(["rekordbox", "match"], capsys)
    data = env["data"]
    assert code == 0 and data["entries"] == [] and data["rekordbox"]["state"] == "unreadable"
    assert data["text"] == words.REKORDBOX_PROBLEM["db_version"]
    assert data["rekordbox"]["state_text"] == words.REKORDBOX_STATE["unreadable"] and data["rekordbox"]["writing"] is False


def test_match_while_a_writer_holds_the_lock_never_opens_master_db(lib, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", [{"path": str(lib.root / LOSSY)}]).parent))
    monkeypatch.setattr(master, "open_read", lambda *a, **k: pytest.fail("master.db was opened"))
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("master.db was opened"))
    with rb_lock.writer_lock(lib.support):
        code, env = data_of(["rekordbox", "match"], capsys)
    data = env["data"]
    assert code == 0 and data["rekordbox"]["writing"] is True and data["rekordbox"]["state"] == "unreadable"
    assert data["entries"] == [] and data["text"] == words.WRITING_WORDS


def test_match_needs_a_music_folder(tmp_path, capsys):
    code, env = data_of(["rekordbox", "match"], capsys)  # conftest: no Setup done
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")


def test_the_counts_helper_is_the_commands_counts_and_none_when_rekordbox_cannot_be_read(
        lib, tmp_path, monkeypatch, elsewhere, capsys):
    from discjockey.cli import bind
    api = bind.default()
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    counts = api._match_counts(library.load_state(lib))
    _, env = data_of(["rekordbox", "match"], capsys)
    assert counts == env["data"]["counts"]
    with rb_lock.writer_lock(lib.support):
        assert api._match_counts(library.load_state(lib)) is None
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))
    assert api._match_counts(library.load_state(lib)) is None


# --- library superseded ---

def test_superseded_lists_the_files_their_size_and_what_rekordbox_still_holds(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    code, env = data_of(["library", "superseded"], capsys)
    data = env["data"]
    assert code == 0 and env["outcome"] == "ok"
    assert [f["rel_path"] for f in data["files"]] == [
        "Superseded/Hard_Bounce/Old.mp3", "Superseded/Hard_Bounce/Spare.mp3", "Superseded/Other/Old2.mp3"]  # no .hidden
    assert [f["rekordbox"] for f in data["files"]] == [1, 0, 1]
    assert [f["size"] for f in data["files"]] == [5, 10, 5] and data["files"][0]["size_text"] == "1 MB"
    assert data["files"][0]["path"] == str(lib.root / "Superseded/Hard_Bounce/Old.mp3")
    assert (data["total"], data["size"], data["held"]) == (3, 20, 2) and data["size_text"] == "1 MB"
    assert data["note"] == words.DELETE_SUPERSEDED
    assert data["text"] == "3 files in Superseded/, 1 MB; rekordbox still uses 2 of them."
    assert data["rekordbox"]["state"] == "ready"
    assert env["next"] == [{"run": cmd("open folder Superseded"), "why": "show them in the Finder"},
                           {"run": cmd("rekordbox match"), "why": "which rekordbox tracks still use them"}]
    assert cli.main(["open", "folder", "Superseded", "--print"]) == 0  # the first next step is a command that runs
    assert str(lib.root / "Superseded") in capsys.readouterr().out
    assert cli.main(["library", "superseded"]) == 0
    captured = capsys.readouterr()
    assert words.DELETE_SUPERSEDED in captured.out and "Next: " in captured.err


def test_superseded_without_a_rekordbox_hold_has_one_next_step(lib, tmp_path, monkeypatch, capsys):
    put(lib.root, "Superseded/Mine/a.mp3")
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))
    code, env = data_of(["library", "superseded"], capsys)
    assert code == 0 and env["data"]["held"] == 0 and env["data"]["rekordbox"]["state"] == "none"
    assert env["data"]["text"] == "1 file in Superseded/, 1 MB; rekordbox uses none of them."
    assert [n["run"] for n in env["next"]] == [cmd("open folder Superseded")]


def test_superseded_does_not_guess_when_rekordbox_cannot_be_read(lib, tmp_path, monkeypatch, capsys):
    put(lib.root, "Superseded/Mine/a.mp3")
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", [{"path": str(lib.root / "Superseded/Mine/a.mp3")}]).parent))
    monkeypatch.setattr(master, "open_read", lambda *a, **k: pytest.fail("master.db was opened"))
    with rb_lock.writer_lock(lib.support):
        code, env = data_of(["library", "superseded"], capsys)
    data = env["data"]
    assert code == 0 and data["rekordbox"]["writing"] is True and data["files"][0]["rekordbox"] == 0 and data["held"] == 0
    assert data["text"] == "1 file in Superseded/, 1 MB."  # no word of what rekordbox uses


def test_superseded_with_no_folder_or_an_empty_one_says_it_is_empty(lib, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", []).parent))
    code, env = data_of(["library", "superseded"], capsys)
    assert code == 0 and env["data"]["files"] == [] and env["data"]["text"] == words.NO_SUPERSEDED and env["next"] == []
    assert env["data"]["note"] == words.DELETE_SUPERSEDED and env["data"]["total"] == 0
    (lib.root / "Superseded").mkdir()
    _, env = data_of(["library", "superseded"], capsys)
    assert env["data"]["files"] == [] and env["data"]["text"] == words.NO_SUPERSEDED


def test_superseded_pages_through_the_envelope(lib, tmp_path, monkeypatch, elsewhere, capsys):
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    _, env = data_of(["library", "superseded", "--limit", "2"], capsys)
    assert len(env["data"]["files"]) == 2 and env["page"] == {
        "list": "files", "offset": 0, "limit": 2, "total": 3, "next_offset": 2}


def test_the_size_helper_is_what_the_command_prints(lib, tmp_path, monkeypatch, elsewhere, capsys):
    from discjockey.cli import bind
    api = bind.default()
    assert api._superseded_size() == (0, 0)  # no folder yet
    with_tracks(lib, tmp_path, monkeypatch, elsewhere)
    _, env = data_of(["library", "superseded"], capsys)
    assert api._superseded_size() == (env["data"]["total"], env["data"]["size"]) == (3, 20)
