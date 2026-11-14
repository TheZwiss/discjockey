"""The console commands of issue 33's stage D (discjockey/convert_cmd.py; plan stage D §2, §5 D5): `convert` and `rename`
through `cli.main` on a library and a fixture rekordbox built in tmp_path (tests/batch_helpers.py `make_own_lib`).
Every scope, the `--in` forms, `--dry-run` changing nothing, exit codes 0-5, `nothing_to_do`, `bad_args`, the facts fill
before a plan, and `batch list | show | resume | undo` / `rekordbox checked --batch` on a stopped convert batch. Nothing
real is read: the music folder and rekordbox come from `DISCJOCKEY_SUPPORT` / `DISCJOCKEY_REKORDBOX`."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime

import pytest

from batch_helpers import Lib, make_own_lib, needs_ffmpeg, use
from discjockey import batch_cmd, batches, cli, convert_cmd, db, library
from discjockey.events import CancelToken
from discjockey.library import load_state
from discjockey.rekordbox import backup as rbbackup
from discjockey.rekordbox import process
from discjockey.rekordbox import session as rbsession

pytestmark = needs_ffmpeg

OK, FAILED, NO_LIBRARY, BUSY, REKORDBOX_OPEN, STOPPED = 0, 1, 2, 3, 4, 5
# make_own_lib's songs, by index: 0 mp3 (in rekordbox), 1 mp3_free, 2 clean (a messy name), 3 clean_free, 4 named (a
# clean AIFF at its clean name), 5 chain (an AIFF 24/96 at its clean name, in rekordbox)
KINDS = ["mp3", "mp3_free", "clean", "clean_free", "named", "chain"]
CLEAN = "Library/A/Artist - Song {i}.aiff"


def apart(lib: Lib) -> None:
    """The fixture's files of one kind hold the same bytes, which To-do shows as a duplicate group (whose decision comes
    first, and the CDJ group leaves its songs out): every file gets a content key of its own, so the tests are about the
    convert side only, and the one that is about the duplicate groups puts two together again."""
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET content_key = 'own:' || id")


def make(tmp_path, monkeypatch, kinds: list[str] = KINDS) -> Lib:
    lib = make_own_lib(tmp_path, monkeypatch, kinds)
    use(lib, monkeypatch)
    apart(lib)
    return lib


def run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(argv: list[str], capsys) -> tuple[int, dict]:
    code, out, _err = run([*argv, "--json"], capsys)
    return code, json.loads(out)          # exactly one JSON object on stdout


def rekordbox_open(monkeypatch, on: bool = True) -> None:
    monkeypatch.setattr(process, "running", lambda: on)


def n_batches(lib: Lib) -> int:
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batches(conn)[1]


def untouched(lib: Lib):
    """Everything a command could change: the music files, rekordbox's library, the records (library.db byte for byte),
    the batches, the backups."""
    return (lib.music(), lib.dump(), lib.paths.db_file.read_bytes(), n_batches(lib), rbbackup.backups(lib.paths),
            load_state(lib.paths)["tracks"])


def final(lib: Lib, i: int) -> str:
    """Where song i's file ends (a lossy file that was converted lands in not_lossless/)."""
    return (CLEAN.replace("A/", "A/not_lossless/") if lib.olds[i].endswith(".mp3") else CLEAN).format(i=i)


def forget_facts(lib: Lib) -> None:
    """The library as a console-only user has it from before schema 8: no stored audio facts."""
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")


def set_rate(lib: Lib, i: int, rate: int) -> None:
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_rate = ? WHERE id = ?", (rate, db.file_id_at(conn, lib.olds[i])))


@contextmanager
def _no_ctrl_c(token: CancelToken):
    yield


REAL_INTERRUPTIBLE, REAL_PROGRESS = batch_cmd._interruptible, convert_cmd._progress


def normal(monkeypatch) -> None:
    """No Stop any more: the real Ctrl-C handling and progress (never `monkeypatch.undo()`: it would also drop the
    environment that points the tests away from the real rekordbox)."""
    monkeypatch.setattr(batch_cmd, "_interruptible", REAL_INTERRUPTIBLE)
    monkeypatch.setattr(convert_cmd, "_progress", REAL_PROGRESS)


def stopping(monkeypatch, *, after: int) -> None:
    """Ctrl-C once `after` files are done (0: before the first): the batch's token is cancelled while file `after + 1`
    starts, which the batch notices before the one after it."""
    seen: dict = {}

    @contextmanager
    def fake(token: CancelToken):
        seen["token"] = token
        if not after:
            token.cancel()
        yield

    monkeypatch.setattr(batch_cmd, "_interruptible", fake)
    real = REAL_PROGRESS

    def progress(plan):
        emit = real(plan)

        def tripped(event):
            emit(event)
            if after and getattr(event, "track_id", None) and event.done == after - 1:
                seen["token"].cancel()
        return tripped

    monkeypatch.setattr(convert_cmd, "_progress", progress)


# --- no music folder, bad arguments ---

COMMANDS = [["convert", "t1"], ["convert", "--all", "lossless"], ["convert", "--all", "cdj", "--dry-run"],
            ["rename", "t1"], ["rename", "--all"], ["rename", "--all", "--dry-run"]]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a))
def test_no_music_folder_is_exit_2(argv, capsys):
    code, data = run_json(argv, capsys)           # conftest: an empty support folder, so Setup was never done
    assert code == NO_LIBRARY
    assert (data["ok"], data["kind"], data["reason"]) == (False, "refused", "no_library")
    assert "music folder" in data["message"]


@pytest.mark.parametrize("argv, words", [
    (["convert", "--all", "cdj", "--in", "unlisted"], "--all cdj"),
    (["convert", "t1", "--in", "unlisted"], "--in narrows --all"),
    (["rename", "t1", "--in", "unlisted"], "--in narrows --all"),
    (["convert", "--all", "lossless", "--in", "playlist:"], "--in is playlist:<name>, folder:<path> or unlisted"),
    (["rename", "--all", "--in", "somewhere"], "--in is playlist:<name>, folder:<path> or unlisted"),
], ids=lambda v: v if isinstance(v, str) else " ".join(v))
def test_bad_args_is_exit_1_and_nothing_is_read(argv, words, tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    before = untouched(lib)
    for extra in ([], ["--dry-run"]):
        code, data = run_json([*argv, *extra], capsys)
        assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "bad_args")
        assert words in data["message"]
    assert untouched(lib) == before


def test_songs_or_all_but_not_both_and_not_neither(capsys):
    for argv in (["convert"], ["rename"], ["convert", "t1", "--all", "cdj"], ["rename", "t1", "--all"],
                 ["convert", "--all", "everything"]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 2, argv
        capsys.readouterr()


# --- --dry-run ---

def test_dry_run_makes_the_plan_and_changes_nothing_and_takes_no_lock(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    before = untouched(lib)
    with library.run_lock(lib.paths.lock), rbsession.writer_lock(lib.paths.support):    # busy would be exit 3
        code, data = run_json(["convert", "--all", "lossless", "--dry-run"], capsys)
        assert code == OK and data["ok"] is True and data["dry_run"] is True and set(data) == {"ok", "dry_run", "plan"}
        plan = data["plan"]
        assert set(plan) == {"scope", "items", "skipped", "waiting", "kinds", "lossy", "total", "space",
                             "superseded_bytes", "rekordbox"}
        assert plan["scope"] == {"kind": "lossless", "view": "all", "key": None, "label": "All tracks"}
        assert [(i["track"], i["action"], i["kind"]) for i in plan["items"]] == [
            (lib.tracks[2], "rename", "name"), (lib.tracks[3], "rename", "name"), (lib.tracks[5], "convert", "aiff_hires")]
        assert plan["items"][0]["path"] == "Library/A/Messy 2.aiff" and plan["items"][0]["new_path"] == final(lib, 2)
        assert plan["skipped"] == [] and plan["waiting"] == [] and plan["total"] == 3 and plan["lossy"] == 0
        assert [(k["kind"], k["n"]) for k in plan["kinds"]] == [("aiff_hires", 1), ("name", 2)]
        assert plan["rekordbox"] == {"state": "ready", "running": False, "needs_closed": True}
        [place] = plan["space"]
        assert set(place) == {"drive", "needed", "free", "enough"} and place["needed"] > 0 and place["enough"] is True
        code, out, err = run(["convert", "--all", "lossless", "--dry-run"], capsys)
    assert code == OK and err == ""
    assert "Clean name only  Artist - Song 2  →  Artist - Song 2.aiff" in out
    assert "AIFF 24-bit or above 44.1 kHz → 16-bit  Artist - Song 5  →  Artist - Song 5.aiff" in out
    assert "3 files would be changed:" in out and "Your originals (" in out and "go to Superseded/" in out
    assert out.rstrip().endswith("Dry run: nothing was changed. The real run checks each file again.")
    assert untouched(lib) == before and not (lib.paths.root / ".discjockey" / "rekordbox").exists()


def test_dry_run_says_when_rekordbox_must_be_closed_and_when_space_is_short(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "clean_free"])
    rekordbox_open(monkeypatch)
    code, out, _ = run(["convert", *lib.tracks, "--dry-run"], capsys)
    assert code == OK and "rekordbox is open. Quit rekordbox" in out
    assert "2 of these are lossy" not in out and "1 of these is lossy: an AIFF made from them" in out
    monkeypatch.setattr("discjockey.convert.free_space", lambda folder: 1000)
    code, out, _ = run(["convert", *lib.tracks, "--dry-run"], capsys)
    assert ". Not enough space on" in out and " needed, 1 MB free" in out
    code, data = run_json(["convert", *lib.tracks, "--dry-run"], capsys)
    assert data["plan"]["space"][0]["enough"] is False and data["plan"]["rekordbox"]["running"] is True


def test_dry_run_with_files_in_rekordbox_closed_needs_no_closing_for_files_it_does_not_hold(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3_free", "clean_free"])
    rekordbox_open(monkeypatch)
    code, data = run_json(["convert", "--all", "lossless", "--dry-run"], capsys)
    assert code == OK and data["plan"]["rekordbox"] == {"state": "ready", "running": True, "needs_closed": False}


def test_a_named_song_is_listed_with_its_own_words_when_left_as_it_is(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["convert", lib.tracks[0], lib.tracks[4], "nope", "--dry-run"], capsys)
    assert code == OK
    plan = data["plan"]
    assert plan["scope"]["label"] == "Selection" and [i["track"] for i in plan["items"]] == [lib.tracks[0]]
    assert [(s["track"], s["reason"]) for s in plan["skipped"]] == [(lib.tracks[4], "named_already"),
                                                                    ("nope", "file_missing")]
    assert plan["skipped"][0]["message"] == "A clean AIFF with its clean name already."
    code, out, _ = run(["convert", lib.tracks[0], lib.tracks[4], "--dry-run"], capsys)
    assert "MP3 → AIFF  Artist - Song 0  →  Artist - Song 0.aiff" in out
    assert "Left as it is: Artist - Song 4 (A clean AIFF with its clean name already.)" in out


def test_convert_of_one_song_decides_between_convert_and_name_and_rename_asks_rename_alone(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    for i, convert_action, rename_why in ((0, "convert", "needs_convert"), (2, "rename", None), (5, "convert",
                                                                                                  "needs_convert")):
        code, data = run_json(["convert", lib.tracks[i], "--dry-run"], capsys)
        assert [x["action"] for x in data["plan"]["items"]] == [convert_action], i
        code, data = run_json(["rename", lib.tracks[i], "--dry-run"], capsys)
        plan = data["plan"]
        assert [s["reason"] for s in plan["skipped"]] == ([rename_why] if rename_why else []), i
        assert [x["action"] for x in plan["items"]] == ([] if rename_why else ["rename"]), i
    assert "Convert to AIFF gives it its clean name too" in data["plan"]["skipped"][0]["message"]


def test_rename_all_plans_only_the_names(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["rename", "--all", "--dry-run"], capsys)
    plan = data["plan"]
    assert code == OK and [(i["track"], i["action"]) for i in plan["items"]] == [(lib.tracks[2], "rename"),
                                                                                 (lib.tracks[3], "rename")]
    assert plan["skipped"] == [] and plan["space"] == [] and plan["superseded_bytes"] == 0
    assert plan["scope"]["kind"] == "lossless" and plan["scope"]["view"] == "all"


def test_the_in_forms_narrow_the_view(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    lib.paths.playlists_file.write_text("Empty Mix = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    (lib.paths.root / "Library" / "B").mkdir()            # a folder on disk that holds no file
    for where, tracks in (("unlisted", [2, 3, 5]), ("folder:Library/A", [2, 3, 5]), ("folder:Library/B", []),
                          ("playlist:Empty Mix", [])):
        code, data = run_json(["convert", "--all", "lossless", "--in", where, "--dry-run"], capsys)
        assert code == OK, where
        assert [i["track"] for i in data["plan"]["items"]] == [lib.tracks[i] for i in tracks], where
        view, _, key = where.partition(":")
        assert data["plan"]["scope"]["view"] == view and data["plan"]["scope"]["key"] == (key or None), where
    code, out, _ = run(["convert", "--all", "lossless", "--in", "folder:Library/B", "--dry-run"], capsys)
    assert code == OK and "Nothing to change: these are clean AIFFs already." in out
    code, data = run_json(["rename", "--all", "--in", "unlisted", "--dry-run"], capsys)
    assert code == OK and data["plan"]["total"] == 2


@pytest.mark.parametrize("argv, words", [
    (["convert", "--all", "lossless", "--in", "playlist:Hard Bouncee"], "No playlist called “Hard Bouncee”."),
    (["convert", "--all", "lossless", "--in", "folder:Library/Techo"], "No folder at Library/Techo."),
    (["convert", "--all", "lossless", "--in", "folder:/Volumes/Nowhere/Crate"], "No folder at /Volumes/Nowhere/Crate."),
    (["rename", "--all", "--in", "playlist:Hard Bouncee"], "No playlist called “Hard Bouncee”."),
    (["rename", "--all", "--in", "folder:Library/Techo"], "No folder at Library/Techo."),
], ids=lambda v: v if isinstance(v, str) else " ".join(v))
def test_an_in_name_that_does_not_exist_is_bad_args_not_nothing_to_change(argv, words, tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    lib.paths.playlists_file.write_text("Hard Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    before = untouched(lib)
    for extra in ([], ["--dry-run"]):
        code, data = run_json([*argv, *extra], capsys)
        assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "bad_args")
        assert data["message"] == words
    code, out, _ = run([*argv, "--dry-run"], capsys)
    assert code == FAILED and words in out and "Nothing to change" not in out
    assert untouched(lib) == before                      # no batch, no lock work, no file moved


def test_a_playlist_name_is_found_in_any_case(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    lib.paths.playlists_file.write_text("Hard Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    code, data = run_json(["convert", "--all", "lossless", "--in", "playlist:hard bounce", "--dry-run"], capsys)
    assert code == OK and data["plan"]["items"] == []


def test_the_cdj_group_is_the_files_cdjs_wont_play_well(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["convert", "--all", "cdj", "--dry-run"], capsys)
    assert code == OK and data["plan"]["items"] == [] and data["plan"]["scope"]["label"] == "Won't play well on CDJs"
    set_rate(lib, 5, 192000)                                # a 192 kHz file: CDJs stop earlier
    code, data = run_json(["convert", "--all", "cdj", "--dry-run"], capsys)
    [item] = data["plan"]["items"]
    assert code == OK and (item["track"], item["action"]) == (lib.tracks[5], "convert") and item["cdj"]["short"]
    assert data["plan"]["scope"] == {"kind": "cdj", "label": "Won't play well on CDJs"}


def test_the_cdj_group_leaves_out_the_songs_of_a_listed_duplicate_group_as_the_hub_does(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    for i in (0, 1, 5):
        set_rate(lib, i, 192000)                            # CDJs refuse all three
    with db.connect(lib.paths.db_file) as conn:             # songs 0 and 1 hold the same bytes: a duplicate group
        conn.execute("UPDATE files SET content_key = 'same' WHERE id IN (?, ?)",
                     (db.file_id_at(conn, lib.olds[0]), db.file_id_at(conn, lib.olds[1])))
        [group] = db.duplicate_groups(conn)
    code, data = run_json(["convert", "--all", "cdj", "--dry-run"], capsys)
    assert code == OK and [i["track"] for i in data["plan"]["items"]] == [lib.tracks[5]]   # its decision comes first
    assert data["plan"]["total"] == 1
    with db.connect(lib.paths.db_file) as conn:             # answered (keep both): the songs are in the CDJ group again
        db.set_decision(conn, "keep_both", group.id, "", "keep", datetime.now())
    code, data = run_json(["convert", "--all", "cdj", "--dry-run"], capsys)
    assert sorted(i["track"] for i in data["plan"]["items"]) == sorted(lib.tracks[i] for i in (0, 1, 5))


# --- the facts fill before a plan ---

def facts_of(lib: Lib) -> list:
    with db.connect(lib.paths.db_file) as conn:
        return conn.execute("SELECT id, file_codec, file_rate, file_bits, file_kbps FROM files ORDER BY id").fetchall()


def test_a_dry_run_fills_the_missing_facts_first_under_the_lock(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    expected = facts_of(lib)
    forget_facts(lib)
    assert all(row[1] is None for row in facts_of(lib))
    music, dump = lib.music(), lib.dump()
    with library.run_lock(lib.paths.lock):                  # the fill is a write: a run holding the lock is busy
        code, data = run_json(["convert", "--all", "lossless", "--dry-run"], capsys)
        assert code == BUSY and (data["ok"], data["kind"], data["message"]) == (False, "busy", batch_cmd.LOCK_HELD)
    assert all(row[1] is None for row in facts_of(lib))
    code, out, err = run(["convert", "--all", "lossless", "--dry-run"], capsys)
    assert code == OK and "3 files would be changed" in out
    assert err.splitlines()[0] == "Reading what your files are: 0 of 6" and err.splitlines()[-1].endswith("6 of 6")
    assert [row[1:] for row in facts_of(lib)] == [row[1:] for row in expected]       # what the import would store
    assert (lib.music(), lib.dump()) == (music, dump)       # only reading the files: nothing else changed
    code, out, err = run(["rename", "--all", "--dry-run"], capsys)                   # nothing to fill now: no lock
    assert code == OK and err == ""
    with library.run_lock(lib.paths.lock):
        assert run(["rename", "--all", "--dry-run"], capsys)[0] == OK


def test_a_file_that_cannot_be_read_is_marked_once_so_a_dry_run_takes_no_lock_after_it(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    forget_facts(lib)
    (lib.paths.root / lib.olds[3]).write_bytes(b"not audio at all" * 20)     # ffprobe finds no sound in it
    code, out, err = run(["rename", "--all", "--dry-run"], capsys)           # the fill reads every file once
    assert code == OK and err.splitlines()[0] == "Reading what your files are: 0 of 6"
    with db.connect(lib.paths.db_file) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM files WHERE facts_failed IS NOT NULL")] == [4]
        assert db.facts_missing(conn) == 0
    with library.run_lock(lib.paths.lock):                                    # nothing to fill now: no lock needed
        code, out, err = run(["rename", "--all", "--dry-run"], capsys)
        assert code == OK and err == ""
        assert run(["convert", "--all", "lossless", "--dry-run"], capsys)[0] == OK


def test_a_run_fills_the_missing_facts_before_it_plans(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    forget_facts(lib)
    code, data = run_json(["convert", "--all", "lossless"], capsys)          # no facts: the plan would be empty
    assert code == OK and (data["state"], data["done"]) == ("done", 3)
    assert [r["action"] for r in data["results"]] == ["rename", "rename", "convert"]
    assert all(row[1] is not None for row in facts_of(lib)[:2])


def test_ctrl_c_during_the_fill_is_exit_5_and_nothing_is_planned(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    forget_facts(lib)
    stopping(monkeypatch, after=0)
    before = lib.music(), lib.dump()
    for argv in (["convert", "--all", "lossless"], ["rename", "--all", "--dry-run"]):
        code, data = run_json(argv, capsys)
        assert code == STOPPED and (data["ok"], data["kind"], data["message"]) == (False, "stopped", convert_cmd.STOPPED_WORDS)
    assert (lib.music(), lib.dump()) == before and n_batches(lib) == 0


# --- convert and rename runs ---

def test_convert_songs_is_one_batch_started_by_the_user(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, out, err = run(["convert", lib.tracks[0], lib.tracks[1], lib.tracks[2]], capsys)
    assert code == OK
    assert out.splitlines()[:3] == ["Done: Artist - Song 0 → Artist - Song 0.aiff",
                                    "Done: Artist - Song 1 → Artist - Song 1.aiff",
                                    "Done: Artist - Song 2 → Artist - Song 2.aiff"]
    assert "Made 2 files AIFF, gave 1 file its clean name." in out and "left as they are" not in out
    assert err.splitlines() == ["Converting 1 of 3: Artist – Song 0", "Converting 2 of 3: Artist – Song 1",
                                "Renaming 3 of 3: Artist – Song 2"]
    for i in range(3):
        assert lib.entry(i)["path"] == final(lib, i) and (lib.paths.root / final(lib, i)).is_file()
    assert lib.row(0)["FolderPath"].endswith("not_lossless/Artist - Song 0.aiff") and lib.row(2)["FolderPath"].endswith(
        "A/Artist - Song 2.aiff")
    with db.connect(lib.paths.db_file) as conn:
        row = db.aiff_batch(conn, 1)
    assert (row.kind, row.started_by, row.scope, row.state) == ("convert", "user", "console", "done")
    assert [(i.action, i.state) for i in row.items] == [("convert", "done"), ("convert", "done"), ("rename", "done")]


def test_the_json_of_a_run_is_the_batch(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["convert", lib.tracks[0], lib.tracks[2]], capsys)
    assert code == OK and data["ok"] is True
    assert set(data) == {"ok", "batch", "state", "stop_reason", "total", "done", "skipped", "failed", "results", "backup"}
    assert (data["batch"], data["state"], data["total"], data["done"]) == (1, "done", 2, 2)
    first, second = data["results"]
    assert set(first) == {"track", "action", "state", "reason", "message", "path", "rekordbox"}
    assert (first["action"], first["state"], first["path"], first["rekordbox"]) == (
        "convert", "done", final(lib, 0), {"entries": ["1"], "kept": []})
    assert (second["action"], second["path"]) == ("rename", final(lib, 2))
    assert data["backup"] and [b.id for b in rbbackup.backups(lib.paths)] == [data["backup"]]


def test_make_all_lossless_files_aiff_is_started_by_make_aiff_and_the_cdj_group_by_cdj_all(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["convert", "--all", "lossless", "--in", "folder:Library/A"], capsys)
    assert code == OK and [(r["track"], r["action"]) for r in data["results"]] == [
        (lib.tracks[2], "rename"), (lib.tracks[3], "rename"), (lib.tracks[5], "convert")]
    assert lib.entry(5)["path"] == final(lib, 5) and lib.entry(2)["path"] == final(lib, 2)
    assert lib.row(5)["FolderPath"].endswith("A/Artist - Song 5.aiff")
    assert (lib.paths.root / "Superseded/A/Artist - Song 5.aiff").is_file()          # the chain's original
    set_rate(lib, 0, 192000)                                                          # an mp3 whose stored facts say 192 kHz
    code, data = run_json(["convert", "--all", "cdj"], capsys)
    assert code == OK and [r["track"] for r in data["results"]] == [lib.tracks[0]]
    with db.connect(lib.paths.db_file) as conn:
        assert [(b.kind, b.started_by, b.scope) for b in (db.aiff_batch(conn, 1), db.aiff_batch(conn, 2))] == [
            ("convert", "make_aiff", "console"), ("convert", "cdj_all", "console")]


def test_rename_all_gives_the_names_and_is_started_by_the_user(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    before = lib.entry(5)["path"], lib.entry(0)["path"]
    code, out, err = run(["rename", "--all"], capsys)
    assert code == OK
    assert out.splitlines()[-1] == "Gave 2 files their clean name."          # no USB step: the file itself stayed
    assert err.splitlines() == ["Renaming 1 of 2: Artist – Song 2", "Renaming 2 of 2: Artist – Song 3"]
    assert [lib.entry(i)["path"] for i in (2, 3)] == [final(lib, 2), final(lib, 3)]
    assert (lib.entry(5)["path"], lib.entry(0)["path"]) == before          # a file that needs a Convert is not a Rename's
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_batch(conn, 1).started_by == "user"
    code, data = run_json(["rename", "--all"], capsys)                       # all named now
    assert code == FAILED and data["reason"] == "nothing_to_do"


# --- nothing to do, skipped, refused ---

def test_nothing_to_do_is_exit_1_with_the_plan(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["named", "mp3"])
    before = untouched(lib)
    code, data = run_json(["rename", "--all"], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "nothing_to_do")
    assert data["message"] == "Nothing to change: these are clean AIFFs already."
    assert data["batch"] is None and data["results"] == [] and data["plan"]["total"] == 0
    code, out, _ = run(["convert", "--all", "cdj"], capsys)
    assert code == FAILED and out.strip() == "Nothing to change: these are clean AIFFs already."
    # one named song: its own words
    code, data = run_json(["convert", lib.tracks[1]], capsys)
    assert code == OK                                                          # the mp3 converts: not nothing
    code, data = run_json(["convert", lib.tracks[1]], capsys)                  # a clean AIFF with its name now
    assert code == FAILED and data["reason"] == "nothing_to_do"
    assert data["message"] == "A clean AIFF with its clean name already."
    assert [s["reason"] for s in data["plan"]["skipped"]] == ["named_already"]
    code, out, _ = run(["rename", lib.tracks[0]], capsys)
    assert code == FAILED and out.strip() == "A clean AIFF with its clean name already."
    assert before[3] == 0 and n_batches(lib) == 1                              # only the one real convert made a batch


def test_several_songs_left_as_they_are_say_so_and_are_exit_1_after_the_rest_ran(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    code, data = run_json(["convert", lib.tracks[0], lib.tracks[4], "nope"], capsys)
    assert code == FAILED and data["ok"] is True
    assert (data["total"], data["done"], data["skipped"], data["failed"]) == (3, 1, 2, 0)
    assert [(r["track"], r["state"], r["reason"]) for r in data["results"]] == [
        (lib.tracks[0], "done", None), (lib.tracks[4], "skipped", "named_already"), ("nope", "skipped", "file_missing")]
    code, out, _ = run(["convert", lib.tracks[3], lib.tracks[4]], capsys)
    assert code == FAILED and "Skipped: Artist - Song 4 (A clean AIFF with its clean name already.)" in out
    assert "Gave 1 file its clean name." in out and "1 left as they are." in out and "not upgraded" not in out
    nothing, data = run_json(["convert", lib.tracks[4], "nope"], capsys)
    assert nothing == FAILED and (data["reason"], data["message"]) == (
        "nothing_to_do", "Nothing to change: these are clean AIFFs already.")
    code, out, _ = run(["convert", lib.tracks[4], "nope"], capsys)
    assert out.count("Left as it is:") == 2


def test_a_batch_where_every_item_is_refused_says_its_own_words_not_upgraded(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "clean_free"])
    real = batches.start

    def start_then_lose_the_files(*args, **kw):                  # the answers change between the plan and the run
        batch_id = real(*args, **kw)
        for old in lib.olds:
            (lib.paths.root / old).unlink()
        return batch_id

    monkeypatch.setattr(batches, "start", start_then_lose_the_files)
    code, data = run_json(["convert", *lib.tracks], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["message"]) == (False, "refused", str(batches.Refused(
        batches.result_of(lib.paths, 1))))
    assert data["message"] == "None of these can be changed right now." and data["batch"] == 1
    assert [r["state"] for r in data["results"]] == ["skipped", "skipped"]
    assert "upgraded" not in data["message"]


# --- exit codes ---

def test_the_library_lock_held_is_exit_3_and_nothing_starts(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    before = untouched(lib)
    for argv in (["convert", lib.tracks[0]], ["convert", "--all", "lossless"], ["convert", "--all", "cdj"],
                 ["rename", "--all"], ["rename", lib.tracks[2]]):
        with library.run_lock(lib.paths.lock):
            code, data = run_json(argv, capsys)
        assert code == BUSY, argv
        assert (data["ok"], data["kind"], data["message"]) == (False, "busy", batch_cmd.LOCK_HELD), argv
    assert untouched(lib) == before


def test_rekordbox_lock_held_leaves_the_batch_stopped_and_resumable(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "clean"])
    before = lib.music(), lib.dump()
    with rbsession.writer_lock(lib.paths.support):
        code, data = run_json(["convert", *lib.tracks], capsys)
        assert code == BUSY and (data["ok"], data["kind"], data["message"]) == (False, "busy", rbsession.BUSY)
        assert (data["state"], data["stop_reason"], data["done"]) == ("stopped", "busy", 0)
    assert (lib.music(), lib.dump()) == before
    code, data = run_json(["batch", "resume", str(data["batch"])], capsys)
    assert code == OK and (data["state"], data["done"]) == ("done", 2)


def test_rekordbox_open_is_exit_4_and_resume_finishes_after_it_quit(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    rekordbox_open(monkeypatch)
    before = lib.music(), lib.dump()
    code, data = run_json(["convert", "--all", "lossless"], capsys)
    assert code == REKORDBOX_OPEN and (data["ok"], data["kind"], data["reason"]) == (False, "rekordbox_open", "rekordbox_open")
    assert (data["state"], data["stop_reason"], data["done"], data["total"]) == ("stopped", "rekordbox_open", 0, 3)
    assert (lib.music(), lib.dump()) == before and data["backup"] is None
    code, out, _ = run(["batch", "list"], capsys)
    assert "stopped, rekordbox_open" in out and "3 left" in out
    code, out, _ = run(["rename", "--all"], capsys)                       # the same two files again: a new try, a new batch
    assert code == REKORDBOX_OPEN and "discjockey batch resume 2" in out
    rekordbox_open(monkeypatch, False)
    code, data = run_json(["batch", "resume", "2"], capsys)
    assert code == OK and (data["state"], data["done"]) == ("done", 2)
    code, data = run_json(["batch", "resume", "1"], capsys)                # batch 1 gave those two up (later_batch)
    assert (code, data["state"], data["done"], data["skipped"]) == (FAILED, "done", 1, 2)


def test_one_named_song_that_meets_rekordbox_open_is_closed_not_left_to_resume(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch)
    rekordbox_open(monkeypatch)
    code, data = run_json(["convert", lib.tracks[0]], capsys)
    assert code == REKORDBOX_OPEN and data["kind"] == "rekordbox_open" and data["state"] == "done"
    assert [(r["state"], r["reason"]) for r in data["results"]] == [("skipped", "rekordbox_open")]
    code, out, _ = run(["batch", "list"], capsys)
    assert "stopped" not in out


def test_files_rekordbox_does_not_hold_run_while_rekordbox_is_open(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3_free", "clean_free"])
    rekordbox_open(monkeypatch)
    code, data = run_json(["convert", *lib.tracks], capsys)
    assert code == OK and data["done"] == 2 and rbbackup.backups(lib.paths) == []


def test_a_library_rekordbox_cannot_read_refuses_with_its_own_words(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "clean"])
    lib.place.db.write_bytes(b"not a database")
    before = lib.music()
    code, data = run_json(["convert", lib.tracks[0]], capsys)
    assert code == FAILED and data["reason"] == "nothing_to_do" and data["plan"]["waiting"][0]["reason"] == "rekordbox_unreadable"
    assert "Choose New track" not in data["message"] and "can't open this rekordbox version's library" in data["message"]
    code, data = run_json(["rename", "--all", "--dry-run"], capsys)
    assert code == OK and data["plan"]["items"] == [] and data["plan"]["waiting"][0]["n"] == 1
    assert lib.music() == before


def test_stop_is_exit_5_and_resume_goes_on(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3_free", "clean"])
    stopping(monkeypatch, after=0)
    before = lib.music(), lib.dump()
    code, data = run_json(["convert", *lib.tracks], capsys)
    assert code == STOPPED and (data["ok"], data["kind"]) == (False, "stopped")
    assert (data["state"], data["stop_reason"], data["done"]) == ("stopped", "stop", 0)
    assert data["message"] == "Stopped after 0 of 3." and [r["state"] for r in data["results"]] == ["planned"] * 3
    assert (lib.music(), lib.dump()) == before
    normal(monkeypatch)
    code, done = run_json(["batch", "resume", str(data["batch"])], capsys)
    assert code == OK and (done["state"], done["done"]) == ("done", 3)


# --- batch list | show | resume | undo and rekordbox checked --batch on a convert batch ---

def test_batch_commands_work_on_a_stopped_convert_batch(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "clean", "mp3_free"])
    stopping(monkeypatch, after=1)
    code, out, err = run(["convert", *lib.tracks], capsys)
    assert code == STOPPED
    assert out.splitlines()[0] == "Done: Artist - Song 0 → Artist - Song 0.aiff"
    assert "Waiting: Artist - Song 1" in out and "Stopped after 1 of 3." in out
    assert "Resume it with: discjockey batch resume 1" in out
    code, data = run_json(["batch", "list"], capsys)
    [row] = data["batches"]
    assert (row["batch"], row["kind"], row["started_by"], row["state"], row["stop_reason"], row["done"], row["planned"]) == (
        1, "convert", "user", "stopped", "stop", 1, 2)
    code, out, _ = run(["batch", "list"], capsys)
    assert "stopped, stop  1 of 3 done, 2 left  (user)" in out
    code, out, _ = run(["batch", "show", "1"], capsys)
    assert code == OK and "Done: Artist - Song 0" in out and "Waiting: Artist - Song 2" in out
    assert "Made 1 file AIFF." in out
    # "Done, checked in rekordbox" for the batch's done tracks
    code, data = run_json(["rekordbox", "checked", "--batch", "1"], capsys)
    assert code == OK and data["checked"] == [lib.tracks[0]] and data["not_checked"] == []
    assert lib.entry(0).get("rekordbox_check") is None
    normal(monkeypatch)
    code, data = run_json(["batch", "resume", "1"], capsys)
    assert code == OK and (data["state"], data["done"], data["batch"]) == ("done", 3, 1)
    assert [r["action"] for r in data["results"]] == ["convert", "rename", "convert"]
    done_files = lib.music()
    code, data = run_json(["batch", "undo", "1"], capsys)        # song 0 was checked in rekordbox: its undo is gone
    assert code == FAILED and (data["total"], data["undone"], data["refused"]) == (3, 2, 1)
    assert lib.entry(1)["path"] == lib.olds[1] and lib.entry(2)["path"] == lib.olds[2]
    assert lib.entry(0)["path"] == final(lib, 0)
    assert lib.music() != done_files


def test_undo_of_a_chain_item_gives_the_original_file_back(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["chain", "clean"])
    original = (lib.paths.root / lib.olds[0]).read_bytes()
    code, data = run_json(["convert", "--all", "lossless"], capsys)
    assert code == OK and data["done"] == 2 and (lib.paths.root / "Superseded/A/Artist - Song 0.aiff").read_bytes() == original
    code, data = run_json(["batch", "undo", "1"], capsys)
    assert code == OK and (data["total"], data["undone"], data["refused"]) == (2, 2, 0)
    assert (lib.paths.root / lib.olds[0]).read_bytes() == original and lib.entry(0)["path"] == lib.olds[0]
    assert lib.row(0)["FolderPath"].endswith("A/Artist - Song 0.aiff") and lib.entry(1)["path"] == lib.olds[1]
    assert not (lib.paths.root / "Superseded/A/Artist - Song 0.aiff").exists()
    code, out, _ = run(["batch", "show", "1"], capsys)
    assert "Undone: Artist - Song 0" in out and "Undone: Artist - Song 1" in out
