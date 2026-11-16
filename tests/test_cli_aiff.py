"""Group V1.13 (issue 39, design §5.2, §5.3, §7.1): the AIFF commands and the file facts they read.

Part a (the engine side): `library facts [--dry-run]` through the command line, the facts a dry run reads in memory
(`aiff_plan` / `HubApi.aiff_plan`: up to 50 files, never stored; more is `refused`, `facts_missing`), `HubApi.resolve(
"collection", ...)`, and `plan_id` on `convert`, `rename` and `make_aiff` (a run with a plan runs only its items). The
page of `library facts` is pinned by `tests/cli_golden/library_facts.txt`. A job's worker runs in this process
(`inline_workers` of tests/test_cli_upgrade.py)."""
from __future__ import annotations

import hashlib
import json
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
