"""Group V1.13 (issue 39, design §5.2, §5.3, §7.1): the AIFF commands and the file facts they read.

Part a (the engine side): `library facts [--dry-run]` through the command line, the facts a dry run reads in memory
(`aiff_plan` / `HubApi.aiff_plan`: up to 50 files, never stored; more is `refused`, `facts_missing`), `HubApi.resolve(
"collection", ...)`, and `plan_id` on `convert`, `rename` and `make_aiff` (a run with a plan runs only its items). The
page of `library facts` is pinned by `tests/cli_golden/library_facts.txt`. A job's worker runs in this process
(`inline_workers` of tests/test_cli_upgrade.py)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import hub_helpers
from batch_helpers import make_own_lib, needs_ffmpeg
from convert_helpers import EXACT, OWN, song
from discjockey import aiff_plan, db, importer, library, quality
from discjockey.cli import bind
from discjockey.events import CancelToken
from discjockey.hub import plan_store
from discjockey.hub.api import CliApi
from discjockey.library import Paths
from hub_helpers import choose_music, make_root, wait_job
from rekordbox_helpers import save_library
from test_cli_upgrade import inline_workers, run, run_json  # noqa: F401 - the fixture and helpers of the other command tests

FIXTURES = Path(__file__).parent / "fixtures"
OK, FAILED, BAD_ARGS, BUSY, REFUSED = 0, 1, 2, 3, 7
NOTHING = "Nothing to change: these are clean AIFFs already."


# --- a library of own files whose facts were never stored ---

def own_library(tmp_path, monkeypatch, files: list[tuple[str, bytes | None]], *, flac: bool = False) -> Paths:
    """One own song per file `(name, bytes)` under Library/A/ (`None`: a real MP3, `tests/fixtures/clicks-lame.mp3`), with
    no stored audio facts: a library from before they were kept. `flac`: the songs say they are lossless."""
    paths = choose_music(tmp_path, monkeypatch)
    paths.data.mkdir(parents=True, exist_ok=True)
    songs = {}
    for i, (name, data) in enumerate(files):
        file = paths.root / "Library" / "A" / name
        file.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            shutil.copyfile(FIXTURES / "clicks-lame.mp3", file)
        else:
            file.write_bytes(data)
        extra = {"status": "lossless", "source_format": None} if flac else {}
        songs[f"t{i:03d}aaaaa"] = song(f"Library/A/{name}", title=f"Song {i}", **{**OWN, **extra})
    save_library(paths, songs)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")
    return paths


def facts_stored(paths: Paths) -> list[tuple]:
    with db.connect(paths.db_file, read_only=True) as conn:
        return conn.execute("SELECT id, file_codec, file_rate, file_bits, facts_failed FROM files ORDER BY id").fetchall()


def hashes(*folders: Path, skip: tuple[Path, ...] = ()) -> dict[str, str]:
    """Every file below `folders` (but not below `skip`) by its path and the hash of its bytes."""
    out = {}
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not any(path.is_relative_to(s) for s in skip):
                out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def fake_probe(path):
    """What ffprobe says of a FLAC: no real audio needed."""
    return quality.AudioInfo("flac", 44100, 30.0, kbps=900, bits=16)


# --- importer: the probing and the storing are two things ---

def test_read_facts_reads_in_memory_and_store_facts_writes(tmp_path, monkeypatch):
    paths = own_library(tmp_path, monkeypatch, [("a.mp3", None), ("b.mp3", None), ("c.mp3", b"no sound in here")])
    with db.connect(paths.db_file) as conn:
        rows = db.files_without_facts(conn)
    before = paths.db_file.read_bytes()
    read = list(importer.read_facts(rows))
    assert [(f.audio.codec if f.audio else None, f.failed) for f in read] == [("mp3", False), ("mp3", False), (None, True)]
    assert paths.db_file.read_bytes() == before  # the probing never touched library.db
    with db.connect(paths.db_file) as conn:
        assert importer.store_facts(conn, read) == 2
    stored = facts_stored(paths)
    assert [row[1] for row in stored] == ["mp3", "mp3", None] and stored[2][4] is not None  # the third is marked
    with db.connect(paths.db_file) as conn:
        assert db.facts_missing(conn) == 0  # a marked file no longer counts


def test_a_missing_ffprobe_marks_nothing(tmp_path, monkeypatch):
    paths = own_library(tmp_path, monkeypatch, [("a.mp3", None)])

    def no_ffprobe(path):
        raise FileNotFoundError("ffprobe")
    with db.connect(paths.db_file) as conn:
        assert importer.fill_facts(paths, probe=no_ffprobe) == 0
        assert db.facts_missing(conn) == 1  # tried again next time


def test_a_stop_keeps_the_facts_read_so_far(tmp_path, monkeypatch):
    paths = own_library(tmp_path, monkeypatch, [("a.mp3", None), ("b.mp3", None), ("c.mp3", None)])
    token, seen = CancelToken(), []

    def probe(path):
        seen.append(path)
        if len(seen) == 2:
            token.cancel()
        return quality.probe(path)
    from discjockey.events import Cancelled
    with pytest.raises(Cancelled):
        importer.fill_facts(paths, probe=probe, token=token)
    assert [row[1] for row in facts_stored(paths)] == ["mp3", "mp3", None]


# --- library facts ---

@pytest.fixture
def three(tmp_path, monkeypatch, inline_workers):
    return own_library(tmp_path, monkeypatch, [("a.mp3", None), ("b.mp3", None), ("c.mp3", None)])


def test_a_dry_run_says_how_many_files_lack_facts_and_writes_nothing(three, capsys):
    before = hashes(three.support, three.root)
    code, env = run_json(["library", "facts", "--dry-run"], capsys)
    assert (code, env["outcome"], env["data"]) == (OK, "ok", {"total": 3}), env
    assert hashes(three.support, three.root) == before  # not a byte, plans/ and cache/ included
    assert not (three.support / "plans").exists()  # a count is no plan


def test_library_facts_stores_the_missing_facts_and_a_second_run_has_nothing_to_do(three, capsys):
    code, env = run_json(["library", "facts"], capsys)
    assert (code, env["outcome"], env["job"] is not None) == (OK, "ok", True), env
    assert env["data"] == {"total": 3, "filled": 3, "unreadable": 0}
    assert env["message"] == "Read the facts of 3 files."
    assert [row[1:4] for row in facts_stored(three)] == [("mp3", 44100, None)] * 3
    code, env = run_json(["library", "facts"], capsys)
    assert (code, env["outcome"]) == (OK, "ok") and env["data"] == {"total": 0, "filled": 0, "unreadable": 0}
    assert env["message"] == "Nothing to read: Discjockey knows the facts of every file already."
    code, env = run_json(["library", "facts", "--dry-run"], capsys)
    assert env["data"] == {"total": 0}


def test_a_file_with_no_sound_is_marked_once_and_said(tmp_path, monkeypatch, inline_workers, capsys):
    own_library(tmp_path, monkeypatch, [("a.mp3", None), ("b.mp3", b"not music")])
    code, env = run_json(["library", "facts"], capsys)
    assert (code, env["outcome"]) == (OK, "ok") and env["data"] == {"total": 2, "filled": 1, "unreadable": 1}
    assert env["message"] == "Read the facts of 1 file. 1 file could not be read and stays without facts."
    assert run_json(["library", "facts", "--dry-run"], capsys)[1]["data"] == {"total": 0}  # it is not asked again


def test_library_facts_waits_for_the_library_lock_and_a_dry_run_does_not(three, capsys):
    before = facts_stored(three)
    with library.run_lock(three.lock):
        code, env = run_json(["library", "facts"], capsys)
        assert (code, env["outcome"]) == (BUSY, "busy"), env
        code, env = run_json(["library", "facts", "--dry-run"], capsys)
        assert (code, env["outcome"], env["data"]) == (OK, "ok", {"total": 3})
    assert facts_stored(three) == before


def test_library_facts_without_a_music_folder_is_refused(tmp_path, monkeypatch, capsys, inline_workers):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "empty-support"))
    for argv in (["library", "facts"], ["library", "facts", "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), argv


def test_golden_the_page_of_library_facts(three, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    code, out, err = run(["library", "facts"], capsys)
    assert code == OK and "library_facts" in WRITES
    check_golden("library_facts", out.replace(str(tmp_path), "<tmp>"))


# --- a dry run reads missing facts in memory, up to 50 files ---

def api_of(paths: Paths, probe=fake_probe, **kw) -> tuple[CliApi, object]:
    rec = hub_helpers.Recorder()
    api = CliApi(paths.support, rec, hub_helpers.services(**kw))
    hub_helpers._MADE.append(api)
    api._attach(paths)
    api._jobs.keep_awake = hub_helpers._no_awake
    api._svc.probe = probe
    return api, rec


def flacs(tmp_path, monkeypatch, n: int) -> Paths:
    return own_library(tmp_path, monkeypatch, [(f"Artist - Song {i}.flac", f"flac {i}".encode()) for i in range(n)], flac=True)


@pytest.mark.parametrize("scope", [{"kind": "lossless", "view": "all", "key": None},
                                   {"kind": "lossless", "view": "folder", "key": "Library/A"},
                                   {"kind": "cdj"}], ids=["all", "folder", "cdj"])
def test_fifty_files_without_facts_are_read_in_memory_and_nothing_is_stored(tmp_path, monkeypatch, scope):
    paths = flacs(tmp_path, monkeypatch, 50)
    api, _ = api_of(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    skip = (paths.support / "plans", paths.support / "cache")
    before = hashes(paths.support, paths.root, skip=skip)
    answer = api.aiff_plan(scope)
    assert answer["ok"], answer
    total = answer["plan"]["total"]
    assert total == (0 if scope["kind"] == "cdj" else 50)  # FLACs are lossless files to convert; a CDJ plays them
    assert hashes(paths.support, paths.root, skip=skip) == before  # T9: not a byte outside plans/ and cache/
    assert all(row[1] is None for row in facts_stored(paths))  # the facts are read, never stored


def test_the_cdj_group_is_found_from_facts_read_in_memory(tmp_path, monkeypatch):
    paths = own_library(tmp_path, monkeypatch, [(f"Artist - Song {i}.mp3", f"mp3 {i}".encode()) for i in range(5)])
    api, _ = api_of(paths, probe=lambda p: quality.AudioInfo("mp3", 44100, 30.0, kbps=400),
                    rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    answer = api.aiff_plan({"kind": "cdj"})
    assert answer["ok"] and answer["plan"]["total"] == 5  # 400 kbps: a file the club players refuse
    assert all(row[1] is None for row in facts_stored(paths))


def test_the_window_plans_on_stored_facts_when_more_than_fifty_files_lack_them(tmp_path, monkeypatch):
    """The refusal is the command line's: the window has no action that reads facts, so its Convert panel plans on what
    is stored (files without facts left out, as before this group) instead of dead-ending."""
    paths = flacs(tmp_path, monkeypatch, 52)
    with db.connect(paths.db_file) as conn:  # one file has its facts stored
        conn.execute("UPDATE files SET file_codec = 'flac', file_rate = 44100, file_bits = 16, file_kbps = 900 "
                     "WHERE id = (SELECT MIN(id) FROM files)")
    api, _ = hub_helpers.make_api(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    api._svc.probe = fake_probe
    skip = (paths.support / "plans", paths.support / "cache")
    before = hashes(paths.support, paths.root, skip=skip)
    for scope in ({"kind": "lossless", "view": "all", "key": None}, {"kind": "cdj"}):
        answer = api.aiff_plan(scope)
        assert answer["ok"], (scope, answer)
        assert answer["plan"]["total"] == (0 if scope["kind"] == "cdj" else 1), scope  # only the file with facts
    assert hashes(paths.support, paths.root, skip=skip) == before
    cli, _ = api_of(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    assert cli.aiff_plan({"kind": "lossless", "view": "all", "key": None})["reason"] == "facts_missing"  # still the command line's


def test_fifty_one_files_without_facts_are_refused_and_name_library_facts(tmp_path, monkeypatch):
    paths = flacs(tmp_path, monkeypatch, 51)
    api, _ = api_of(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    skip = (paths.support / "plans", paths.support / "cache")
    before = hashes(paths.support, paths.root, skip=skip)
    for scope in ({"kind": "lossless", "view": "all", "key": None}, {"kind": "cdj"},
                  {"kind": "tracks", "tracks": [f"t{i:03d}aaaaa" for i in range(51)]}):
        answer = api.aiff_plan(scope)
        assert not answer["ok"], (scope, answer)
        assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "refused", "refused",
                                                                                      "facts_missing"), scope
        assert answer["next"][0]["run"] == "library facts" and answer["data"] == {"missing": 51, "most": 50}
        assert "51 files" in answer["message"]
    assert hashes(paths.support, paths.root, skip=skip) == before
    assert wait_job(api, _, api.fill_facts()).ok  # the explicit write the answer names ...
    assert api.aiff_plan({"kind": "lossless", "view": "all", "key": None})["plan"]["total"] == 51  # ... and then the plan


def test_a_file_that_is_marked_unreadable_does_not_count_towards_the_fifty(tmp_path, monkeypatch):
    paths = flacs(tmp_path, monkeypatch, 51)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET facts_failed = size || ':' || mtime_ns WHERE id = 1")
    api, _ = api_of(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    assert api.aiff_plan({"kind": "lossless", "view": "all", "key": None})["ok"]


def test_a_view_asks_only_for_its_own_files(tmp_path, monkeypatch):
    paths = flacs(tmp_path, monkeypatch, 51)
    api, _ = api_of(paths, rekordbox_place=lambda: None, rekordbox_running=lambda: False)
    other = paths.root / "Library" / "B"
    other.mkdir()
    state = library.load_state(paths)
    for key in list(state["tracks"])[:2]:  # two songs live in another folder: the view of A has 49
        name = Path(state["tracks"][key]["path"]).name
        (paths.root / state["tracks"][key]["path"]).rename(other / name)
        state["tracks"][key]["path"] = f"Library/B/{name}"
    library.save_state(paths, state)
    answer = api.aiff_plan({"kind": "lossless", "view": "folder", "key": "Library/A"})
    assert answer["ok"] and answer["plan"]["total"] == 49


# --- resolve("collection") ---

@pytest.fixture
def lib(tmp_path, monkeypatch):
    make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return bind.default()


def test_the_collection_kinds_resolve_to_a_view_and_a_key(lib):
    answer = lib.resolve("collection", ["all", "unlisted", "playlist:Hard_Bounce", "playlist:hard_bounce",
                                        "Powertrance", "folder:Library/Hard_Bounce"])
    assert answer["ok"] and answer["kind"] == "collection"
    assert answer["resolved"] == [
        {"view": "all", "key": None}, {"view": "unlisted", "key": None},
        {"view": "playlist", "key": "Hard_Bounce"}, {"view": "playlist", "key": "Hard_Bounce"},  # as playlists.txt spells it
        {"view": "playlist", "key": "Powertrance"}, {"view": "folder", "key": "Library/Hard_Bounce"}]


def test_a_folder_inside_the_music_folder_resolves_whether_typed_absolute_or_not(lib, tmp_path):
    for typed in (str(tmp_path / "Library" / "Hard_Bounce"), "Library/Hard_Bounce", "Library/Hard_Bounce/"):
        assert lib.resolve("collection", [f"folder:{typed}"])["resolved"] == [{"view": "folder", "key": "Library/Hard_Bounce"}]


def test_an_unknown_playlist_or_folder_is_bad_args_unknown_id_in_the_old_words(lib):
    for text, words in (("playlist:Nope", "No playlist called “Nope”."), ("Nope", "No playlist called “Nope”."),
                        ("folder:Library/Nope", "No folder at Library/Nope.")):
        answer = lib.resolve("collection", [text])
        assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "bad_args", "bad_args",
                                                                                      "unknown_id"), text
        assert answer["message"] == words


def test_a_collection_of_another_shape_is_a_usage_error(lib):
    answer = lib.resolve("collection", ["song:x"])
    assert (answer["outcome"], answer["reason"]) == ("bad_args", "usage")
    assert "playlist:<name>" in answer["message"]


# --- plan_id on convert, rename and make_aiff ---

@pytest.fixture
def hub(tmp_path, monkeypatch):
    def build(kinds, running=False):
        lib = make_own_lib(tmp_path, monkeypatch, kinds)
        with db.connect(lib.paths.db_file) as conn:
            conn.execute("UPDATE files SET content_key = 'own:' || id")  # no duplicate group takes a song out
        api, rec = api_of(lib.paths, probe=quality.probe, compare=lambda a, b: EXACT,
                          rekordbox_running=lambda: running, rekordbox_place=lambda: lib.place)
        return lib, api, rec
    return build


def plan_of(api, scope, command="aiff convert") -> str:
    """The dry run's plan as the command line saves it (the plan id of `data`)."""
    plan_id = api.save_plan(command, api.aiff_plan(scope), command)
    assert plan_id is not None
    return plan_id


def edit_rate(lib, i, rate):
    """File i's stored rate: a 16-bit clean AIFF at another rate is no clean AIFF any more (its item changes)."""
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_rate = ? WHERE id = ?", (rate, db.file_id_at(conn, lib.olds[i])))


def batch_rows(lib):
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batches(conn)[0]


@needs_ffmpeg
def test_a_plans_save_keys_each_item_by_its_song(hub):
    lib, api, rec = hub(["clean_free", "clean_free"])
    scope = {"kind": "tracks", "tracks": lib.tracks}
    plan_id = plan_of(api, scope)
    plan = plan_store.load(lib.paths.support, plan_id, str(lib.paths.root))
    assert list(plan.items) == lib.tracks and plan.items[lib.tracks[0]]["action"] == "rename"
    assert plan.command == "aiff convert"


@needs_ffmpeg
def test_rename_with_a_plan_runs_the_plans_named_songs_that_stand_and_lists_the_new_one(hub):
    lib, api, rec = hub(["clean_free", "clean_free", "clean_free"])
    a, b, c = lib.tracks
    plan_id = plan_of(api, {"kind": "tracks", "tracks": [a, b]}, "aiff rename")
    edit_rate(lib, 1, 48000)  # b is another answer now; c has an item and was not in the plan
    f = wait_job(api, rec, api.rename([a, b, c], plan_id))
    assert f.ok, f
    data = f.result
    assert [(r["track"], r["action"], r["state"], r["reason"]) for r in data["results"]] == [
        (a, "rename", "done", None), (b, "rename", "skipped", "changed")]
    assert (data["total"], data["done"], data["skipped"], data["new_since_plan"]) == (2, 1, 1, [c])
    assert lib.entry(0)["path"].endswith("Artist - Song 0.aiff") and lib.entry(2)["path"].endswith("Messy 2.aiff")
    assert [(row.started_by, row.scope, row.via) for row in batch_rows(lib)] == [("user", "selection", "terminal")]


@needs_ffmpeg
def test_convert_with_a_plan_leaves_out_the_songs_it_was_not_asked_about(hub):
    lib, api, rec = hub(["clean_free", "clean_free"])
    a, b = lib.tracks
    plan_id = plan_of(api, {"kind": "tracks", "tracks": [a, b]})
    f = wait_job(api, rec, api.convert([a], "library", plan_id))  # b is in the plan and was not named: no `changed` row
    assert f.ok and [(r["track"], r["state"]) for r in f.result["results"]] == [(a, "done")]
    assert lib.entry(1)["path"].endswith("Messy 1.aiff")
    assert f.result["total"] == 1 and "new_since_plan" not in f.result


@needs_ffmpeg
def test_make_aiff_with_a_plan_runs_its_items_as_one_batch_started_by_make_aiff(hub):
    lib, api, rec = hub(["clean_free", "clean_free", "clean_free"])
    scope = {"kind": "lossless", "view": "all", "key": None}
    plan_id = plan_of(api, scope)
    edit_rate(lib, 2, 48000)  # the third is another item now
    f = wait_job(api, rec, api.make_aiff(scope, plan_id))
    assert f.ok, f
    assert [(r["state"], r["reason"]) for r in f.result["results"]] == [("done", None), ("done", None), ("skipped", "changed")]
    assert (f.result["total"], f.result["done"]) == (3, 2) and "new_since_plan" not in f.result
    assert [(row.started_by, row.scope, row.state) for row in batch_rows(lib)] == [("make_aiff", "library:all", "done")]


@needs_ffmpeg
def test_the_cdj_groups_convert_all_with_a_plan_is_started_by_cdj_all(hub):
    lib, api, rec = hub(["mp3_free", "mp3_free"])
    with db.connect(lib.paths.db_file) as conn:
        for i in range(2):
            conn.execute("UPDATE files SET file_kbps = 400 WHERE id = ?", (db.file_id_at(conn, lib.olds[i]),))
    plan_id = plan_of(api, {"kind": "cdj"})
    f = wait_job(api, rec, api.make_aiff({"kind": "cdj"}, plan_id))
    assert f.ok and f.result["done"] == 2
    assert [(row.started_by, row.scope) for row in batch_rows(lib)] == [("cdj_all", "todo:cdj")]


@needs_ffmpeg
def test_a_plan_with_nothing_that_stands_ends_done_with_total_zero(hub):
    lib, api, rec = hub(["named"])  # a clean AIFF at its clean name: nothing to change
    scope = {"kind": "lossless", "view": "all", "key": None}
    assert api.aiff_plan(scope)["plan"]["total"] == 0
    plan_id = plan_of(api, scope)
    f = wait_job(api, rec, api.make_aiff(scope, plan_id))
    assert f.ok and (f.result["batch"], f.result["state"], f.result["total"], f.result["done"]) == (None, "done", 0, 0)
    assert api.result_words("make_aiff", f.result)["message"] == NOTHING
    assert batch_rows(lib) == []
    # without a plan the same run is the window's refusal
    assert wait_job(api, rec, api.make_aiff(scope)).problem == "refused"


@needs_ffmpeg
def test_a_plan_none_of_whose_songs_stands_is_changed_and_starts_nothing(hub):
    lib, api, rec = hub(["clean_free", "clean_free"])
    scope = {"kind": "lossless", "view": "all", "key": None}
    plan_id = plan_of(api, scope)
    edit_rate(lib, 0, 48000)
    edit_rate(lib, 1, 48000)
    answer = api.make_aiff(scope, plan_id)
    assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "changed", "refused", "changed")
    assert batch_rows(lib) == []


@needs_ffmpeg
def test_an_empty_plan_with_new_files_since_lists_them_and_does_not_say_nothing_to_change(hub):
    lib, api, rec = hub(["named"])
    scope = {"kind": "lossless", "view": "all", "key": None}
    plan_id = plan_of(api, scope)  # nothing to change then
    with db.connect(lib.paths.db_file) as conn:  # the file is not a clean name any more: an item now
        conn.execute("UPDATE files SET file_rate = 48000")
    f = wait_job(api, rec, api.make_aiff(scope, plan_id))
    assert f.ok and f.result["total"] == 0 and f.result["new_since_plan"] == [lib.tracks[0]]
    assert "message" not in api.result_words("make_aiff", f.result)


def test_library_facts_makes_the_records_and_has_nothing_to_read_in_a_library_with_no_database(tmp_path, monkeypatch):
    paths = choose_music(tmp_path, monkeypatch)
    paths.data.mkdir(parents=True, exist_ok=True)
    api, rec = api_of(paths)
    assert api.facts_preview() == {"ok": True, "total": 0}
    f = wait_job(api, rec, api.fill_facts())
    assert f.ok and f.result == {"total": 0, "filled": 0, "unreadable": 0}


@needs_ffmpeg
def test_an_unknown_or_expired_plan_starts_nothing(hub):
    lib, api, rec = hub(["clean_free"])
    for call in (lambda p: api.convert(lib.tracks, "library", p), lambda p: api.rename(lib.tracks, p),
                 lambda p: api.make_aiff({"kind": "lossless", "view": "all", "key": None}, p)):
        answer = call("plan:0123456789ab")
        assert (answer["ok"], answer["outcome"], answer["reason"]) == (False, "bad_args", "unknown_id")
    other = plan_store.save(lib.paths.support, "aiff convert", "/somewhere/else", {}, {"command": "aiff convert --all"})
    answer = api.make_aiff({"kind": "lossless", "view": "all", "key": None}, other)
    assert (answer["outcome"], answer["reason"]) == ("refused", "plan_expired")
    assert batch_rows(lib) == []


@needs_ffmpeg
def test_the_dry_run_of_a_library_with_facts_missing_is_the_plan_a_run_binds(hub):
    lib, api, rec = hub(["clean_free", "clean_free"])
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")
    scope = {"kind": "lossless", "view": "all", "key": None}
    plan_id = plan_of(api, scope)  # read in memory: two items
    assert len(plan_store.load(lib.paths.support, plan_id, str(lib.paths.root)).items) == 2
    assert all(row[1] is None for row in facts_stored(lib.paths))
    f = wait_job(api, rec, api.make_aiff(scope, plan_id))  # the run stores the facts and then runs both
    assert f.ok and f.result["done"] == 2 and "new_since_plan" not in f.result
    assert all(row[1] is not None for row in facts_stored(lib.paths))


# ======================================================================================================================
# Part b: `aiff convert` and `aiff rename` through the command line, end to end. A job's worker runs in this process
# (`inline_workers`). The legacy `discjockey convert | rename` (convert_cmd.py) is gone; what its tests pinned of the
# engine is pinned here on the new commands (the tally is in the commit message).
# ======================================================================================================================

import discjockey.cli as cli
from batch_helpers import Lib, make_own_lib as make_own_library, use
from discjockey import batches, convert
from discjockey.hub import catalog, select
from discjockey.rekordbox import backup as rbbackup, process
from discjockey.rekordbox import session as rbsession

NEEDS_PERSON, PARTIAL, STOPPED = 4, 6, 5
# make_own_lib's songs, by index: 0 mp3 (in rekordbox), 1 mp3_free, 2 clean (a messy name), 3 clean_free, 4 named (a
# clean AIFF at its clean name), 5 chain (an AIFF 24/96 at its clean name, in rekordbox)
KINDS = ["mp3", "mp3_free", "clean", "clean_free", "named", "chain"]
CLEAN = "Library/A/Artist - Song {i}.aiff"


@pytest.fixture
def world(tmp_path, monkeypatch, inline_workers):
    """`make(kinds)`: a library of own songs and a fixture rekordbox, as the command line finds them. Every file gets a
    content key of its own, so no duplicate group takes a song out (the tests are about the convert side only)."""
    from discjockey.hub.api import CliApi
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, text: text)  # the fixture's keys are not real song keys

    def make(kinds=KINDS) -> Lib:
        found = make_own_library(tmp_path, monkeypatch, kinds)
        use(found, monkeypatch)
        with db.connect(found.paths.db_file) as conn:
            conn.execute("UPDATE files SET content_key = 'own:' || id")
        return found
    return make


def batch_of(found, n=1):
    with db.connect(found.paths.db_file) as conn:
        return db.aiff_batch(conn, n)


def n_batches(found) -> int:
    with db.connect(found.paths.db_file) as conn:
        return db.aiff_batches(conn)[1]


def final(found, i: int) -> str:
    """Where song i's file ends (a lossy file that was converted lands in not_lossless/)."""
    return (CLEAN.replace("A/", "A/not_lossless/") if found.olds[i].endswith(".mp3") else CLEAN).format(i=i)


def untouched(found):
    """Everything a command could change: the music files, rekordbox's library, the records, the batches, the backups."""
    return (found.music(), found.dump(), found.paths.db_file.read_bytes(), n_batches(found), rbbackup.backups(found.paths),
            library.load_state(found.paths)["tracks"])


def rows_of(env):
    return [(r["track"], r["action"], r.get("state")) for r in env["data"]["results"]]


def set_rate(found, i, rate):
    with db.connect(found.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_rate = ? WHERE id = ?", (rate, db.file_id_at(conn, found.olds[i])))


# --- the line: forms, the entry the command picks, `help` ---

def test_help_shows_one_row_for_each_command_and_the_parser_picks_the_entry_by_the_form():
    from discjockey.cli import housekeeping, parser
    index = {c["command"]: c for c in housekeeping.index()}
    assert {"aiff convert", "aiff rename"} <= set(index) and index["aiff convert"]["kind"] == "J"
    assert [e.method for e in parser.commands()[("aiff", "convert")]] == ["convert", "make_aiff", "aiff_plan"]
    assert [e.method for e in parser.commands()[("aiff", "rename")]] == ["rename", "aiff_plan"]
    assert all("--origin" not in c["usage"] and "--only" not in c["usage"] for c in index.values())
    assert {"--all", "--rows", "--in", "--todo", "--dry-run"} <= set(index["aiff convert"]["flags"])
    assert "--plan" in index["aiff convert"]["usage"]


@pytest.mark.parametrize("old", [["convert", "t1"], ["rename", "--all"]])
def test_the_old_words_say_where_they_went(old, capsys):
    code, env = run_json(old, capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "usage") and "aiff " + old[0] in env["message"]


@pytest.mark.parametrize("argv", [["aiff", "convert"], ["aiff", "rename"], ["aiff", "convert", "t1", "--all"],
                                  ["aiff", "rename", "t1", "--rows"], ["aiff", "convert", "--all", "--rows"]])
def test_songs_or_all_or_rows_and_exactly_one_of_them(argv, world, capsys):
    world(["mp3"])
    code, env = run_json(argv, capsys)
    assert code == BAD_ARGS and env["outcome"] == "bad_args" and env["reason"] in ("usage", "conflicting_flags"), env


@pytest.mark.parametrize("argv, words", [
    (["aiff", "convert", "--all", "--todo", "cdj", "--in", "unlisted"], "--in can't narrow it"),
    (["aiff", "convert", "--all", "--todo", "upgrade_ready"], "--all takes --todo cdj"),
    (["aiff", "convert", "t1", "--in", "unlisted"], "narrow --rows"),
    (["aiff", "convert", "t1", "--todo", "cdj"], "narrow --rows"),
    (["aiff", "rename", "t1", "--in", "unlisted"], "narrow --rows"),
    (["aiff", "convert", "--all", "--search", "x"], "--search narrows --rows"),
    (["aiff", "rename", "--all", "--todo", "cdj"], "--todo narrows --rows"),
], ids=lambda v: v if isinstance(v, str) else " ".join(v[1:]))
def test_in_means_nothing_with_named_songs_or_the_cdj_group(argv, words, world, capsys):
    found = world(["mp3"])
    before = untouched(found)
    for extra in ([], ["--dry-run"]):
        code, env = run_json([*argv, *extra], capsys)
        assert code == BAD_ARGS and env["outcome"] == "bad_args" and words in env["message"], env
        assert env["reason"] == ("usage" if "--all takes" in words else "conflicting_flags")
    assert untouched(found) == before and env["job"] is None  # nothing was read, no job started


@pytest.mark.parametrize("argv", [["aiff", "convert", "local:1"], ["aiff", "convert", "--all"], ["aiff", "convert", "--all", "--todo", "cdj"],
                                  ["aiff", "rename", "local:1"], ["aiff", "rename", "--all"], ["aiff", "convert", "local:1", "--dry-run"],
                                  ["aiff", "rename", "--all", "--dry-run"]], ids=lambda a: " ".join(a[1:]))
def test_no_music_folder_is_refused_no_library(argv, capsys, inline_workers):
    code, env = run_json(argv, capsys)  # conftest: an empty support folder, so Setup was never done
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), env
    assert "music folder" in env["message"]


# --- --in: the collections ---

@pytest.mark.parametrize("argv, words", [
    (["--in", "playlist:Hard Bouncee"], "No playlist called “Hard Bouncee”."),
    (["--in", "folder:Library/Techo"], "No folder at Library/Techo."),
    (["--in", "folder:/Volumes/Nowhere/Crate"], "No folder at /Volumes/Nowhere/Crate."),
], ids=lambda v: v if isinstance(v, str) else v[1])
@pytest.mark.parametrize("command", [["aiff", "convert", "--all"], ["aiff", "rename", "--all"]], ids=lambda c: c[1])
def test_an_in_name_that_does_not_exist_is_bad_args_unknown_id_not_nothing_to_change(command, argv, words, world, capsys):
    found = world()
    found.paths.playlists_file.write_text("Hard Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    before = untouched(found)
    for extra in ([], ["--dry-run"]):
        code, env = run_json([*command, *argv, *extra], capsys)
        assert (code, env["outcome"], env["reason"], env["message"]) == (BAD_ARGS, "bad_args", "unknown_id", words), env
    code, out, err = run([*command, *argv, "--dry-run"], capsys)
    assert code == BAD_ARGS and words in err and "Nothing to change" not in out + err
    assert untouched(found) == before  # no batch, no job, no file moved


def test_the_in_forms_narrow_the_view_and_a_playlist_name_is_found_in_any_case(world, capsys):
    found = world()
    found.paths.playlists_file.write_text("Empty Mix = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    (found.paths.root / "Library" / "B").mkdir()  # a folder on disk that holds no file
    for where, tracks in (("all", [2, 3, 5]), ("unlisted", [2, 3, 5]), ("folder:Library/A", [2, 3, 5]),
                          ("folder:Library/B", []), ("playlist:Empty Mix", []), ("playlist:empty mix", []),
                          ("Empty Mix", [])):
        code, env = run_json(["aiff", "convert", "--all", "--in", where, "--dry-run"], capsys)
        assert (code, env["outcome"]) == (OK, "ok"), (where, env)
        assert [i["track"] for i in env["data"]["plan"]["items"]] == [found.tracks[i] for i in tracks], where
        scope = env["data"]["plan"]["scope"]
        view, _, key = where.partition(":")
        if where in ("all", "unlisted", "folder:Library/A", "folder:Library/B"):
            assert (scope["view"], scope["key"]) == (view, key or None), where
    code, out, _ = run(["aiff", "convert", "--all", "--in", "folder:Library/B", "--dry-run"], capsys)
    assert code == OK and re.search(r"Total\s+0\n", out)
    code, env = run_json(["aiff", "rename", "--all", "--in", "unlisted", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["total"] == 2


# --- --dry-run: the plan, and nothing written but the plan ---

def test_a_dry_run_is_the_plan_the_window_shows_and_takes_no_lock_of_its_own(world, capsys):
    found = world()
    before = untouched(found)
    with library.run_lock(found.paths.lock):  # a run holding the library is no reason for a read to wait
        code, env = run_json(["aiff", "convert", "--all", "--dry-run"], capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "aiff convert"), env
    assert env["job"] is not None and env["data"]["plan_id"].startswith("plan:")  # the read ran as a job; its plan is saved
    plan = env["data"]["plan"]
    assert set(plan) == {"scope", "items", "skipped", "waiting", "kinds", "lossy", "total", "space", "superseded_bytes",
                         "rekordbox"}
    assert plan["scope"] == {"kind": "lossless", "view": "all", "key": None, "label": "All tracks"}
    assert [(i["track"], i["action"], i["kind"]) for i in plan["items"]] == [
        (found.tracks[2], "rename", "name"), (found.tracks[3], "rename", "name"), (found.tracks[5], "convert", "aiff_hires")]
    assert plan["items"][0]["path"] == "Library/A/Messy 2.aiff" and plan["items"][0]["new_path"] == final(found, 2)
    assert plan["total"] == 3 and plan["rekordbox"] == {"state": "ready", "running": False, "needs_closed": True}
    assert untouched(found) == before and [p.name for p in (found.paths.support / "plans").iterdir()] == [
        f"{env['data']['plan_id'][5:]}.json"]


def test_a_dry_run_while_a_writer_holds_rekordbox_lock_plans_blind_and_says_writing(world, capsys):
    """The carry item of V1.7's review: master.db is read only while the shared lock is held and never opened under a
    writer's; the plan then takes rekordbox's cached state and says so, as `rekordbox status` and the restore dry run do."""
    found = world(["mp3", "clean"])
    code, env = run_json(["aiff", "convert", *found.tracks, "--dry-run"], capsys)
    assert code == OK and "writing" not in env["data"]["plan"]["rekordbox"]
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["aiff", "convert", *found.tracks, "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["rekordbox"]["writing"] is True
    assert [i["track"] for i in env["data"]["plan"]["items"]] == found.tracks  # still a plan, made without the lookups


def test_a_dry_run_says_when_rekordbox_must_be_closed_and_when_space_is_short(world, capsys, monkeypatch):
    found = world(["mp3", "clean_free"])
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["aiff", "convert", *found.tracks, "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["rekordbox"] == {"state": "ready", "running": True, "needs_closed": True}
    assert env["data"]["plan"]["lossy"] == 1
    monkeypatch.setattr("discjockey.convert.free_space", lambda folder: 1000)
    code, env = run_json(["aiff", "convert", *found.tracks, "--dry-run"], capsys)
    assert env["data"]["plan"]["space"][0]["enough"] is False


def test_files_rekordbox_does_not_hold_need_no_closing(world, capsys, monkeypatch):
    world(["mp3_free", "clean_free"])
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["aiff", "convert", "--all", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["rekordbox"] == {"state": "ready", "running": True, "needs_closed": False}


def test_a_named_song_left_as_it_is_says_its_own_words(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", found.tracks[0], found.tracks[4], "nope", "--dry-run"], capsys)
    assert code == OK
    plan = env["data"]["plan"]
    assert plan["scope"]["label"] == "Selection" and [i["track"] for i in plan["items"]] == [found.tracks[0]]
    assert [(s["track"], s["reason"]) for s in plan["skipped"]] == [(found.tracks[4], "named_already"), ("nope", "file_missing")]
    assert plan["skipped"][0]["message"] == "A clean AIFF with its clean name already."


def test_convert_decides_between_convert_and_name_and_rename_asks_rename_alone(world, capsys):
    found = world()
    for i, convert_action, rename_why in ((0, "convert", "needs_convert"), (2, "rename", None), (5, "convert", "needs_convert")):
        code, env = run_json(["aiff", "convert", found.tracks[i], "--dry-run"], capsys)
        assert [x["action"] for x in env["data"]["plan"]["items"]] == [convert_action], i
        code, env = run_json(["aiff", "rename", found.tracks[i], "--dry-run"], capsys)
        plan = env["data"]["plan"]
        assert [s["reason"] for s in plan["skipped"]] == ([rename_why] if rename_why else []), i
        assert [x["action"] for x in plan["items"]] == ([] if rename_why else ["rename"]), i
    assert "Convert to AIFF gives it its clean name too" in plan["skipped"][0]["message"]


def test_rename_all_plans_only_the_names_of_the_files_it_selects(world, capsys):
    found = world()
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)
    plan = env["data"]["plan"]
    assert code == OK and [(i["track"], i["action"]) for i in plan["items"]] == [(found.tracks[2], "rename"),
                                                                                 (found.tracks[3], "rename")]
    assert plan["skipped"] == [] and plan["space"] == [] and plan["superseded_bytes"] == 0
    assert plan["scope"]["kind"] == "lossless" and plan["scope"]["view"] == "all"  # the collection's plan, as the run selects
    code, env = run_json(["aiff", "rename", "--rows", "--in", "all", "--dry-run"], capsys)  # every row, as `library list` shows it
    plan = env["data"]["plan"]
    assert code == OK and [i["track"] for i in plan["items"]] == [found.tracks[2], found.tracks[3]]
    assert [(s["track"], s["reason"]) for s in plan["skipped"]] == [
        (found.tracks[0], "needs_convert"), (found.tracks[1], "needs_convert"), (found.tracks[4], "named_already"),
        (found.tracks[5], "needs_convert")]


def test_the_cdj_group_is_the_files_cdjs_wont_play_well(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", "--all", "--todo", "cdj", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["items"] == [] and env["data"]["plan"]["scope"]["label"] == "Won't play well on CDJs"
    set_rate(found, 5, 192000)  # a 192 kHz file: CDJs stop earlier
    code, env = run_json(["aiff", "convert", "--all", "--todo", "cdj", "--dry-run"], capsys)
    [item] = env["data"]["plan"]["items"]
    assert code == OK and (item["track"], item["action"]) == (found.tracks[5], "convert") and item["cdj"]["short"]


def test_nothing_selected_by_all_or_rows_is_done_in_the_engines_words(world, capsys):
    found = world(["named", "mp3"])
    code, env = run_json(["aiff", "rename", "--all"], capsys)  # `select` finds none: nothing is started
    assert (code, env["outcome"], env["message"], env["job"]) == (OK, "ok", NOTHING, None), env
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)  # the plan of that collection says it too
    assert (code, env["outcome"], env["message"], env["data"]["plan"]["total"]) == (OK, "ok", NOTHING, 0), env
    found.paths.playlists_file.write_text("Empty Mix = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    for extra in ([], ["--dry-run"]):  # rows that name no song at all
        code, env = run_json(["aiff", "convert", "--rows", "--in", "playlist:Empty Mix", *extra], capsys)
        assert (code, env["outcome"], env["message"], env["job"]) == (OK, "ok", select.NO_ROWS, None), env
    assert n_batches(found) == 0


# --- --dry-run with files whose facts are not stored (design §7.1) ---

@pytest.fixture
def fake_facts(monkeypatch, inline_workers):
    """The workers' api reads the facts of fake files through a fake ffprobe."""
    real = bind.headless

    def headless(resolved, **kw):
        api = real(resolved, **kw)
        api._svc.probe = fake_probe
        return api
    monkeypatch.setattr(bind, "headless", headless)


@pytest.mark.parametrize("n, refused", [(50, False), (51, True)])
def test_a_dry_run_reads_at_most_fifty_files_in_memory_and_writes_nothing_but_its_plan(n, refused, tmp_path, monkeypatch,
                                                                                         capsys, fake_facts):
    paths = flacs(tmp_path, monkeypatch, n)
    skip = (paths.support / "plans", paths.support / "cache", paths.support / "jobs")  # (jobs: the registry's own record)
    before = hashes(paths.support, paths.root, skip=skip)
    code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/A", "--dry-run"], capsys)
    assert hashes(paths.support, paths.root, skip=skip) == before and all(row[1] is None for row in facts_stored(paths))
    if refused:
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "facts_missing"), env
        assert env["next"][0]["run"] == "library facts" and env["data"] == {"missing": 51, "most": 50}
        assert not (paths.support / "plans").exists()
        code, env = run_json(["library", "facts"], capsys)  # the explicit write the answer names ...
        assert code == OK and env["data"]["filled"] == 51
        code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/A", "--dry-run"], capsys)  # ... then the plan
        assert code == OK and env["data"]["plan"]["total"] == 51
    else:
        assert (code, env["outcome"], env["data"]["plan"]["total"]) == (OK, "ok", 50), env
        assert env["data"]["plan_id"].startswith("plan:") and [p.name for p in (paths.support / "plans").iterdir()]


# --- the runs: one AIFF batch, started by ... ---

def test_convert_songs_is_one_batch_started_by_the_user(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", found.tracks[0], found.tracks[1], found.tracks[2]], capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "aiff convert") and env["job"], env
    data = env["data"]
    assert (data["batch"], data["batch_id"], data["state"], data["total"], data["done"]) == (1, "aiff:1", "done", 3, 3)
    assert [(r["track"], r["action"], r["state"]) for r in data["results"]] == [
        (found.tracks[0], "convert", "done"), (found.tracks[1], "convert", "done"), (found.tracks[2], "rename", "done")]
    assert env["message"] == "Made 2 files AIFF, gave 1 file its clean name." and [n["run"] for n in env["next"]][0] == "batch show aiff:1"
    assert data["results"][0]["rekordbox"] == {"entries": ["1"], "kept": []} and data["backup"]
    assert [b.id for b in rbbackup.backups(found.paths)] == [data["backup"]]
    for i in range(3):
        assert found.entry(i)["path"] == final(found, i) and (found.paths.root / final(found, i)).is_file()
    assert found.row(0)["FolderPath"].endswith("not_lossless/Artist - Song 0.aiff")
    assert found.row(2)["FolderPath"].endswith("A/Artist - Song 2.aiff")
    row = batch_of(found)
    assert (row.kind, row.started_by, row.scope, row.via, row.state) == ("convert", "user", "selection", "terminal", "done")
    assert [(i.action, i.state) for i in row.items] == [("convert", "done"), ("convert", "done"), ("rename", "done")]


def scrubbed(out: str, tmp_path) -> str:
    """A page as the golden holds it: the temp folder and the backup's name (the time it was made) said by a word."""
    return re.sub(r"\d{8}T\d{6}Z", "<backup>", out.replace(str(tmp_path), "<tmp>"))


def test_the_page_of_a_run_is_the_batch_and_what_to_do_in_rekordbox(world, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    found = world()
    code, out, err = run(["aiff", "convert", found.tracks[0], found.tracks[2]], capsys)
    assert code == OK and "aiff_convert" in WRITES
    check_golden("aiff_convert", scrubbed(out, tmp_path))
    assert "Made 1 file AIFF, gave 1 file its clean name." in out + err and "Next: batch show aiff:1" in err
    assert "Your turn: " in err and "Then: check done" in err  # the Reload Tag step of a convert


def test_the_page_of_a_rename_run(world, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    found = world()
    code, out, err = run(["aiff", "rename", "--all"], capsys)
    assert code == OK and "aiff_rename" in WRITES
    check_golden("aiff_rename", scrubbed(out, tmp_path))


def test_a_run_by_view_and_by_the_cdj_group_is_started_by_make_aiff_and_cdj_all_and_a_rename_by_the_user(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/A"], capsys)
    assert code == OK and rows_of(env) == [(found.tracks[2], "rename", "done"), (found.tracks[3], "rename", "done"),
                                           (found.tracks[5], "convert", "done")]
    assert found.entry(5)["path"] == final(found, 5) and found.entry(2)["path"] == final(found, 2)
    assert found.row(5)["FolderPath"].endswith("A/Artist - Song 5.aiff")
    assert (found.paths.root / "Superseded/A/Artist - Song 5.aiff").is_file()  # the chain's original
    set_rate(found, 0, 192000)  # an mp3 whose stored facts say 192 kHz
    code, env = run_json(["aiff", "convert", "--all", "--todo", "cdj"], capsys)
    assert code == OK and [r["track"] for r in env["data"]["results"]] == [found.tracks[0]]
    assert [(b.kind, b.started_by, b.scope) for b in (batch_of(found, 1), batch_of(found, 2))] == [
        ("convert", "make_aiff", "library:folder:Library/A"), ("convert", "cdj_all", "todo:cdj")]
    code, env = run_json(["aiff", "rename", "--all"], capsys)  # all named already
    assert (code, env["outcome"], env["message"]) == (OK, "ok", NOTHING) and n_batches(found) == 2


def test_rename_all_gives_the_names_as_a_batch_of_the_user_and_leaves_a_file_that_needs_a_convert(world, capsys):
    found = world()
    before = found.entry(5)["path"], found.entry(0)["path"]
    code, env = run_json(["aiff", "rename", "--all"], capsys)
    assert code == OK and rows_of(env) == [(found.tracks[2], "rename", "done"), (found.tracks[3], "rename", "done")]
    assert [found.entry(i)["path"] for i in (2, 3)] == [final(found, 2), final(found, 3)]
    assert (found.entry(5)["path"], found.entry(0)["path"]) == before  # a file that needs a Convert is not a Rename's
    row = batch_of(found)
    assert (row.started_by, row.scope, row.via) == ("user", "selection", "terminal")
    code, out, err = run(["aiff", "rename", "--all"], capsys)  # all named now
    assert code == OK and NOTHING in out


def test_a_run_with_a_plan_runs_the_plans_items_as_one_batch(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/A", "--dry-run"], capsys)
    plan_id = env["data"]["plan_id"]
    set_rate(found, 3, 48000)  # the fourth is another answer now
    code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/A", "--plan", plan_id], capsys)
    data = env["data"]
    assert (code, env["outcome"]) == (PARTIAL, "partial"), env
    assert [(r["track"], r["state"], r["reason"]) for r in data["results"]] == [  # what ran, then what changed
        (found.tracks[2], "done", None), (found.tracks[5], "done", None), (found.tracks[3], "skipped", "changed")]
    assert (data["total"], data["done"], data["skipped"]) == (3, 2, 1) and "new_since_plan" not in data
    assert batch_of(found).started_by == "make_aiff"


def test_a_rename_run_with_a_plan_runs_the_plans_names_as_a_batch_of_the_user(world, capsys):
    found = world()
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)
    assert code == OK and [i["track"] for i in env["data"]["plan"]["items"]] == [found.tracks[2], found.tracks[3]]
    plan_id = env["data"]["plan_id"]
    set_rate(found, 3, 48000)  # the fourth needs a Convert now: not a Rename's, so `select` no longer names it (the plan does)
    set_rate(found, 4, 48000)  # the fifth, a clean name, is one too: an item that was not in the plan
    code, env = run_json(["aiff", "rename", "--all", "--plan", plan_id], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial"), env  # the plan's fourth song answers `changed`, as for any plan run
    assert rows_of(env) == [(found.tracks[2], "rename", "done"), (found.tracks[3], "rename", "skipped")]
    assert [r["reason"] for r in env["data"]["results"]][1] == "changed" and "new_since_plan" not in env["data"]
    assert (batch_of(found).started_by, batch_of(found).scope) == ("user", "selection")
    # named songs are bound to the plan the same way: the plan's two songs, both another answer now (renamed; needs a
    # Convert), leave nothing that stands
    code, env = run_json(["aiff", "rename", found.tracks[3], found.tracks[2], "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed") and n_batches(found) == 1


def test_a_plan_of_nothing_to_change_ends_ok_with_total_zero_and_the_engines_words(world, capsys):
    found = world(["named", "named"])
    code, env = run_json(["aiff", "convert", "--all", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["total"] == 0
    code, env = run_json(["aiff", "convert", "--all", "--plan", env["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["message"], env["data"]["total"]) == (OK, "ok", NOTHING, 0), env
    assert n_batches(found) == 0
    code, env = run_json(["aiff", "convert", "--all"], capsys)  # without a plan the same run is the window's refusal
    assert (code, env["outcome"], env["message"]) == (REFUSED, "refused", NOTHING)


def test_a_plan_none_of_whose_songs_stands_is_changed_and_a_wrong_plan_is_bad_args(world, capsys):
    found = world(["clean_free", "clean_free"])
    code, env = run_json(["aiff", "convert", "--all", "--dry-run"], capsys)
    plan_id = env["data"]["plan_id"]
    set_rate(found, 0, 48000)
    set_rate(found, 1, 48000)
    code, env = run_json(["aiff", "convert", "--all", "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed") and n_batches(found) == 0
    code, env = run_json(["aiff", "convert", "--all", "--plan", "plan:0123456789ab"], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id")


def test_a_facts_less_library_runs_after_the_run_stores_the_facts(world, capsys):
    found = world()
    with db.connect(found.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")
    code, env = run_json(["aiff", "convert", "--all"], capsys)  # no facts: the plan would be empty without the fill
    assert code == OK and (env["data"]["state"], env["data"]["done"]) == ("done", 3)
    assert [r["action"] for r in env["data"]["results"]] == ["rename", "rename", "convert"]
    assert facts_stored(found.paths)[0][1] is not None


# --- nothing to do, skipped, refused ---

def test_nothing_to_change_is_refused_with_the_engines_words_one_song_in_its_own(world, capsys):
    found = world(["named", "mp3"])
    before = untouched(found)
    code, env = run_json(["aiff", "convert", found.tracks[0]], capsys)
    assert (code, env["outcome"], env["message"]) == (REFUSED, "refused", "A clean AIFF with its clean name already.")
    assert [s["reason"] for s in env["data"]["results"]] and env["data"]["batch"] is None
    code, env = run_json(["aiff", "convert", found.tracks[0], "nope"], capsys)  # two songs left as they are
    assert (code, env["outcome"], env["message"]) == (REFUSED, "refused", "None of these can be changed right now.")
    assert [(r["track"], r["reason"]) for r in env["data"]["results"]] == [(found.tracks[0], "named_already"), ("nope", "file_missing")]
    code, env = run_json(["aiff", "rename", found.tracks[1]], capsys)  # an mp3 needs a Convert, which is not Rename's
    assert (code, env["outcome"]) == (REFUSED, "refused")
    assert untouched(found) == before


def test_several_songs_left_as_they_are_say_so_and_are_partial_after_the_rest_ran(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", found.tracks[0], found.tracks[4], "nope"], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial")
    data = env["data"]
    assert (data["total"], data["done"], data["skipped"], data["failed"]) == (3, 1, 2, 0)
    assert [(r["track"], r["state"], r["reason"]) for r in data["results"]] == [
        (found.tracks[0], "done", None), (found.tracks[4], "skipped", "named_already"), ("nope", "skipped", "file_missing")]


def test_a_batch_where_every_item_is_refused_says_its_own_words(world, capsys, monkeypatch):
    found = world(["mp3", "clean_free"])
    real = batches.start

    def start_then_lose_the_files(*args, **kw):  # the answers change between the plan and the run
        batch_id = real(*args, **kw)
        for old in found.olds:
            (found.paths.root / old).unlink()
        return batch_id

    monkeypatch.setattr(batches, "start", start_then_lose_the_files)
    code, env = run_json(["aiff", "convert", *found.tracks], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused")
    assert env["message"] == "None of these can be changed right now." == str(batches.Refused(batches.result_of(found.paths, 1)))
    assert [r["state"] for r in env["data"]["results"]] == ["skipped", "skipped"] and "upgraded" not in env["message"]


# --- locks and rekordbox ---

@pytest.mark.parametrize("argv", [["aiff", "convert", "{0}"], ["aiff", "convert", "--all"], ["aiff", "convert", "--all", "--todo", "cdj"],
                                  ["aiff", "rename", "--all"], ["aiff", "rename", "{2}"]], ids=lambda a: " ".join(a[1:]))
def test_the_library_lock_held_is_busy_and_nothing_starts(argv, world, capsys):
    found = world()
    before = untouched(found)
    line = [a.format(*found.tracks) for a in argv]
    with library.run_lock(found.paths.lock):
        code, env = run_json(line, capsys)
    assert (code, env["outcome"]) == (BUSY, "busy"), env
    assert untouched(found) == before


def test_rekordbox_lock_held_leaves_the_batch_stopped_and_resumable(world, capsys):
    found = world(["mp3", "clean"])
    before = found.music(), found.dump()
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["aiff", "convert", *found.tracks], capsys)
    assert (code, env["outcome"]) == (BUSY, "busy"), env
    assert (env["data"]["state"], env["data"]["stop_reason"], env["data"]["done"]) == ("stopped", "busy", 0)
    assert (found.music(), found.dump()) == before
    code, env = run_json(["batch", "resume", f"aiff:{env['data']['batch']}"], capsys)
    assert code == OK and (env["data"]["state"], env["data"]["done"]) == ("done", 2)


def test_rekordbox_open_needs_the_person_and_resume_finishes_after_it_quit(world, capsys, monkeypatch):
    found = world()
    monkeypatch.setattr(process, "running", lambda: True)
    before = found.music(), found.dump()
    code, env = run_json(["aiff", "convert", "--all"], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open"), env
    data = env["data"]
    assert (data["state"], data["stop_reason"], data["done"], data["total"]) == ("stopped", "rekordbox_open", 0, 3)
    assert (found.music(), found.dump()) == before and data["backup"] is None
    assert [s["then"] for s in env["person_steps"]] == ["batch resume aiff:1"]
    code, env = run_json(["aiff", "rename", "--all"], capsys)  # the same two files again: a new try, a new batch
    assert (code, env["reason"]) == (NEEDS_PERSON, "rekordbox_open") and n_batches(found) == 2
    monkeypatch.setattr(process, "running", lambda: False)
    code, env = run_json(["batch", "resume", "aiff:2"], capsys)
    assert code == OK and (env["data"]["state"], env["data"]["done"]) == ("done", 2)


def test_one_named_song_that_meets_rekordbox_open_is_closed_not_left_to_resume(world, capsys, monkeypatch):
    found = world()
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["aiff", "convert", found.tracks[0]], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open"), env
    assert env["data"]["state"] == "done" and [(r["state"], r["reason"]) for r in env["data"]["results"]] == [
        ("skipped", "rekordbox_open")]
    assert env["next"] == [] and all(b.state != "stopped" for b in db_batches(found))
    assert found.entry(0)["path"] == found.olds[0]  # nothing changed; the same command works once rekordbox is quit
    monkeypatch.setattr(process, "running", lambda: False)
    assert run_json(["aiff", "convert", found.tracks[0]], capsys)[0] == OK


def db_batches(found):
    with db.connect(found.paths.db_file) as conn:
        return db.aiff_batches(conn)[0]


def test_files_rekordbox_does_not_hold_run_while_rekordbox_is_open(world, capsys, monkeypatch):
    found = world(["mp3_free", "clean_free"])
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["aiff", "convert", *found.tracks], capsys)
    assert code == OK and env["data"]["done"] == 2 and rbbackup.backups(found.paths) == []


def test_a_library_rekordbox_cannot_read_refuses_with_its_own_words(world, capsys):
    found = world(["mp3", "clean"])
    found.place.db.write_bytes(b"not a database")
    before = found.music()
    code, env = run_json(["aiff", "convert", found.tracks[0]], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused") and "can't open this rekordbox version's library" in env["message"]
    assert "Choose New track" not in env["message"]
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["items"] == [] and env["data"]["plan"]["waiting"][0]["n"] == 1
    assert env["message"] is None  # something waits: "nothing to change" would not be true
    assert found.music() == before


def test_stop_ends_the_batch_stopped_and_resume_goes_on(world, capsys, monkeypatch):
    found = world(["mp3", "mp3_free", "clean"])
    seen = {}
    real_headless, real_convert = bind.headless, convert.convert_file

    def headless(resolved, **kw):
        api = real_headless(resolved, **kw)
        if kw.get("job") is not None:
            seen["api"] = api
        return api

    def convert_file(*args, **kw):  # Stop is pressed while the first file is in work: the batch ends before the second
        result = real_convert(*args, **kw)
        seen["api"]._jobs.inline_token.cancel()
        return result
    monkeypatch.setattr(bind, "headless", headless)
    monkeypatch.setattr(convert, "convert_file", convert_file)
    code, env = run_json(["aiff", "convert", *found.tracks], capsys)
    assert (code, env["outcome"]) == (STOPPED, "stopped"), env
    assert (env["data"]["state"], env["data"]["stop_reason"], env["data"]["done"]) == ("stopped", "stop", 1)
    assert [r["state"] for r in env["data"]["results"]] == ["done", "planned", "planned"]
    monkeypatch.setattr(convert, "convert_file", real_convert)
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert code == OK and (env["data"]["state"], env["data"]["done"]) == ("done", 3)


def test_a_dry_run_of_lossy_files_says_they_grow(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", found.tracks[0], found.tracks[2], "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["lossy"] == 1
    assert env["message"] == "1 of these is lossy: an AIFF made from them sounds the same and takes 5–10 times the space."
    code, out, err = run(["aiff", "convert", found.tracks[0], found.tracks[1], "--dry-run"], capsys)
    assert "2 of these are lossy: an AIFF made from them sounds the same and takes 5–10 times the space." in out
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)  # no lossy file in it: no note
    assert code == OK and env["data"]["plan"]["lossy"] == 0 and env["message"] is None


def test_batch_undo_of_a_convert_batch_gives_the_original_files_back(world, capsys):
    found = world(["chain", "clean"])
    original = {p: (found.paths.root / p).read_bytes() for p in found.olds}
    code, env = run_json(["aiff", "convert", "--all"], capsys)
    assert code == OK and sorted(r[1:] for r in rows_of(env)) == [("convert", "done"), ("rename", "done")], env
    assert all(not (found.paths.root / p).exists() for p in found.olds[1:])  # the messy name is gone
    superseded = found.paths.root / "Superseded/A" / Path(found.olds[0]).name
    assert superseded.exists()  # the old file of the Convert waits there until it is undone
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"]) == (OK, "ok") and env["data"]["undone"] == 2, env
    assert {p: (found.paths.root / p).read_bytes() for p in found.olds} == original
    assert not superseded.exists()
    code, env = run_json(["batch", "show", "aiff:1"], capsys)
    assert code == OK and [r["state"] for r in env["data"]["results"]] == ["undone", "undone"], env


def test_a_folder_that_is_no_collection_is_unknown_even_when_the_directory_exists(world, capsys):
    found = world()
    (found.paths.root / "Superseded").mkdir(exist_ok=True)
    (found.paths.root / "Library" / "Empty").mkdir()
    for typed in ("folder:..", "folder:../x", "folder:Superseded", "folder:Library/../Superseded", "folder:."):
        code, env = run_json(["aiff", "convert", "--all", "--in", typed, "--dry-run"], capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id"), (typed, env)
    code, env = run_json(["aiff", "convert", "--all", "--in", "folder:Library/Empty", "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")  # a folder of the Library with nothing in it is still a place


def test_rows_in_a_playlist_nothing_is_called_is_unknown_not_an_empty_selection(world, capsys):
    world()
    for argv in (["aiff", "convert", "--rows", "--in", "playlist:Nope"], ["upgrade", "apply", "--rows", "--in", "playlist:Nope", "--way", "same-track"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id"), (argv, env)


def test_the_text_of_a_dry_run_says_what_would_change(world, capsys):
    found = world()
    code, out, err = run(["aiff", "rename", "--all", "--dry-run"], capsys)
    assert code == OK and "Artist - Song 2" in out and "Messy 2.aiff" in out
    assert err.splitlines()[0].startswith("Job job:") and "Plan id" in out


# --- --rows, and the engine's side of the forms ---

def test_rows_are_every_song_the_listing_shows_and_a_run_of_them_is_the_users(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", "--rows", "--in", "folder:Library/A", "--search", "Song 2", "--dry-run"], capsys)
    assert code == OK and [i["track"] for i in env["data"]["plan"]["items"]] == [found.tracks[2]]
    code, env = run_json(["aiff", "convert", "--rows", "--in", "folder:Library/A", "--search", "Song 2"], capsys)
    assert code == OK and rows_of(env) == [(found.tracks[2], "rename", "done")]
    assert (batch_of(found).started_by, batch_of(found).scope) == ("user", "selection")


def test_select_listing_rename_all_names_the_files_a_rename_would_rename(world):
    from discjockey.cli import bind
    found = world()
    api = bind.default()
    assert api.select_listing({"verb_all": select.RENAME_ALL})["ids"] == [found.tracks[2], found.tracks[3]]
    assert api.select_listing({"verb_all": select.RENAME_ALL, "in": "folder:Library/A"})["ids"] == [found.tracks[2], found.tracks[3]]
    assert api.select_listing({"verb_all": select.RENAME_ALL, "in": "unlisted"})["ids"] == [found.tracks[2], found.tracks[3]]
    nothing = api.select_listing({"verb_all": select.RENAME_ALL, "in": "playlist:Nope"})
    assert (nothing["ok"], nothing["outcome"], nothing["reason"], nothing["message"]) == (
        False, "bad_args", "unknown_id", "No playlist called “Nope”.")
    clash = api.select_listing({"verb_all": select.RENAME_ALL, "search": "x"})  # a verb's "all" is not narrowed
    assert (clash["outcome"], clash["reason"]) == ("bad_args", "conflicting_flags")
    other = api.select_listing({"verb_all": select.UPGRADE_ALL, "in": "all"})  # only Rename all takes `in`
    assert (other["outcome"], other["reason"]) == ("bad_args", "conflicting_flags")
    plan = api.select_listing({"verb_all": select.UPGRADE_ALL, "plan": "plan:0123456789ab"})  # only Rename all takes `plan`
    assert (plan["outcome"], plan["reason"]) == ("bad_args", "conflicting_flags")
    plan = api.select_listing({"in": "all", "plan": "plan:0123456789ab"})
    assert (plan["outcome"], plan["reason"]) == ("bad_args", "conflicting_flags")
    unknown = api.select_listing({"verb_all": select.RENAME_ALL, "plan": "plan:0123456789ab"})
    assert (unknown["outcome"], unknown["reason"]) == ("bad_args", "unknown_id")


def test_aiff_plan_takes_only_rename_or_nothing(world):
    from discjockey.cli import bind
    found = world()
    api = bind.default()
    scope = {"kind": "tracks", "tracks": [found.tracks[0], found.tracks[2]]}
    assert [i["action"] for i in api.aiff_plan(scope)["plan"]["items"]] == ["convert", "rename"]
    plan = api.aiff_plan(scope, "rename")["plan"]
    assert [i["action"] for i in plan["items"]] == ["rename"] and [s["reason"] for s in plan["skipped"]] == ["needs_convert"]
    bad = api.aiff_plan(scope, "convert")
    assert (bad["ok"], bad["kind"], bad["message"]) == (False, "refused", "`only` is rename, or left out.")


def test_the_summary_line_of_a_run_is_the_engines_and_counts_what_was_left(world):
    from discjockey import words
    results = [{"state": "done", "action": "convert"}, {"state": "done", "action": "convert"}, {"state": "done", "action": "rename"},
               {"state": "skipped", "action": "convert"}]
    assert words.aiff_summary(results, 3, 1) == "Made 2 files AIFF, gave 1 file its clean name. 1 left as they are."
    assert words.aiff_summary(results[2:3], 1, 0) == "Gave 1 file its clean name."
    assert words.aiff_summary(results[3:], 0, 1) == "1 left as they are."


def test_call_reaches_the_same_entries_and_its_dry_run_is_the_plan(world, capsys):
    found = world(["mp3", "clean"])
    ids = json.dumps({"track_ids": found.tracks})
    code, env = run_json(["call", "convert", "--args", ids, "--dry-run"], capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "aiff convert") and env["data"]["plan"]["total"] == 2
    code, env = run_json(["call", "aiff_plan", "--args", json.dumps({"scope": {"kind": "tracks", "tracks": found.tracks}, "only": "rename"})], capsys)
    assert (code, env["command"], [i["action"] for i in env["data"]["plan"]["items"]]) == (OK, "aiff rename", ["rename"])
    code, env = run_json(["call", "convert", "--args", json.dumps({"track_ids": found.tracks, "origin": "todo",
                                                                    "plan_id": env["data"]["plan_id"]})], capsys)
    assert code == OK and env["data"]["done"] == 1  # the Rename plan: the mp3, not in it, is left out


def test_the_cdj_groups_convert_all_with_its_plan_is_started_by_cdj_all(world, capsys):
    found = world(["mp3_free", "mp3_free"])
    with db.connect(found.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_kbps = 400")  # the club players refuse both
    code, env = run_json(["aiff", "convert", "--all", "--todo", "cdj", "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["total"] == 2
    code, env = run_json(["aiff", "convert", "--all", "--todo", "cdj", "--plan", env["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 2)
    assert (batch_of(found).started_by, batch_of(found).scope) == ("cdj_all", "todo:cdj")


def test_a_plan_made_on_facts_read_in_memory_still_binds_after_library_facts_stored_them(world, capsys):
    """A scratch library with no stored facts: the dry run plans on facts read in memory, `library facts` stores them, and
    the run binds that plan against answers built from the stored ones. Nothing is `changed`."""
    found = world(["mp3", "mp3_free", "clean_free"])
    with db.connect(found.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")
    code, env = run_json(["aiff", "convert", *found.tracks, "--dry-run"], capsys)
    assert code == OK and env["data"]["plan"]["total"] == 3 and all(row[1] is None for row in facts_stored(found.paths))
    plan_id = env["data"]["plan_id"]
    code, env = run_json(["library", "facts"], capsys)
    assert code == OK and env["data"]["filled"] == 3
    code, env = run_json(["aiff", "convert", *found.tracks, "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["data"]["done"], env["data"]["skipped"]) == (OK, "ok", 3, 0), env
    assert "new_since_plan" not in env["data"]


def test_rename_all_with_a_plan_follows_the_plan_rule_when_nothing_is_selected_any_more(world, capsys):
    """`rename --all --plan P` runs the plan's songs too, not only today's selection (V1.10's rule): an unknown plan is
    `unknown_id` even when no song is left to rename, and a plan none of whose songs stands is `changed`."""
    found = world(["clean_free", "mp3"])
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)
    plan_id = env["data"]["plan_id"]
    assert code == OK and run_json(["aiff", "rename", "--all"], capsys)[0] == OK  # the name was given
    code, env = run_json(["aiff", "rename", "--all", "--plan", "plan:0123456789ab"], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id"), env
    code, env = run_json(["aiff", "rename", "--all", "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed"), env
    assert n_batches(found) == 1
    # without a plan the same call is done: nothing left to rename
    code, env = run_json(["aiff", "rename", "--all"], capsys)
    assert (code, env["outcome"], env["message"]) == (OK, "ok", NOTHING)
    # the same plan, run with the songs named, is the plan rule too
    code, env = run_json(["aiff", "rename", found.tracks[0], "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed")


def test_a_plan_of_other_songs_than_the_named_ones_is_changed_not_ok_with_nothing_done(world, capsys):
    found = world()
    code, env = run_json(["aiff", "convert", found.tracks[1], "--dry-run"], capsys)
    assert code == OK and [i["track"] for i in env["data"]["plan"]["items"]] == [found.tracks[1]]
    before = found.music()
    code, env = run_json(["aiff", "convert", found.tracks[0], "--plan", env["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed"), env
    assert found.music() == before and n_batches(found) == 0


def test_rename_all_with_a_plan_answers_a_plan_song_renamed_since_with_a_changed_row(world, capsys):
    found = world()
    code, env = run_json(["aiff", "rename", "--all", "--dry-run"], capsys)
    plan_id = env["data"]["plan_id"]
    assert code == OK and [i["track"] for i in env["data"]["plan"]["items"]] == [found.tracks[2], found.tracks[3]]
    assert run_json(["aiff", "rename", found.tracks[2]], capsys)[0] == OK  # one of the two was renamed by hand
    code, env = run_json(["aiff", "rename", "--all", "--plan", plan_id], capsys)
    assert (code, env["outcome"], env["data"]["done"], env["data"]["skipped"]) == (6, "partial", 1, 1), env
    assert sorted(rows_of(env)) == sorted([(found.tracks[2], "rename", "skipped"), (found.tracks[3], "rename", "done")])
    assert [r["reason"] for r in env["data"]["results"] if r["state"] == "skipped"] == ["changed"]
