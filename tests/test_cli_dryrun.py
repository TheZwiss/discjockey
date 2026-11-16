"""Group V1.10, part a (issue 39, design §7.1 and §7.2): the call path of a dry run (its plan, its `as_of`, its `next`),
`--plan`, `--yes` and `needs_yes`, and the read-only opens.

No built entry has a `dry_run` or `needs_yes` yet (the groups that build the writes add them), so the call path is tried
through hand-made entries (kind `B`: no worker) whose methods are put on `CliApi` for the test, and never in the
catalogue (T1 and the ceiling test would trip). The selection and `upgrade apply --dry-run` tests are part b's."""
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root

from discjockey import db, library, report as rep, run as run_mod
from discjockey.cli import bind, call
from discjockey.cli.parser import Flags
from discjockey.hub import catalog, plan_store
from discjockey.hub.api import CliApi, cli_first
from discjockey.hub.catalog import Entry

STATE: dict[str, str] = {}  # item key -> what the "engine" says about it today (a test changes it between two calls)
WRITTEN: list[list[str]] = []


def rows(ids):
    return {i: {"key": i, "action": STATE.get(i, "convert")} for i in ids}


def demo_dry(self, ids: list[str]) -> dict:
    return {"items": list(rows(ids).values()), "total": len(ids)}


def demo_write(self, ids: list[str], plan_id: str | None = None) -> dict:
    if plan_id is None:
        WRITTEN.append(list(ids))
        return {"ran": list(ids)}
    plan, bound = self._bind_plan(plan_id, rows(ids))
    WRITTEN.append(list(bound.run))
    return {"ran": list(bound.run), "skipped": [{"key": k, "state": "skipped", "reason": "changed"} for k in bound.changed],
            "new_since_plan": list(bound.new)}


def what_if(self) -> dict:
    return {"limit": 5}  # a what-if: no `items`, so no plan


def change(self) -> dict:
    WRITTEN.append(["change"])
    return {}


def entry(**kw) -> Entry:
    fields = dict(method="demo_write", command=("demo", "write"), kind="B", dry_run="demo_dry")
    return Entry(**{**fields, **kw})


@pytest.fixture
def lib(tmp_path, monkeypatch):
    for fn in (demo_dry, demo_write, what_if, change):
        monkeypatch.setattr(CliApi, fn.__name__, cli_first(fn), raising=False)
    STATE.clear()
    WRITTEN.clear()
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def tree(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, str]:
    """Every file below `root` (but not below `skip`) by its path and the hash of its bytes."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(path.is_relative_to(s) for s in skip):
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def go(e: Entry, args: dict, **flags) -> dict:
    return call.run(e, args, Flags(**flags), api=bind.default())


# --- the plan of a dry run ---

def test_a_dry_run_saves_its_plan_and_says_its_id_in_data(lib):
    env = go(entry(), {"ids": ["a", "b"]}, dry_run=True)
    assert env["outcome"] == "ok" and env["data"]["total"] == 2
    plan_id = env["data"]["plan_id"]
    assert plan_id.startswith("plan:")
    plan = plan_store.load(lib.support, plan_id, str(lib.root))
    assert plan.kind == "demo write" and set(plan.items) == {"a", "b"} and plan.command == "demo write"
    assert WRITTEN == []  # the dry run ran the entry's dry_run method, never the write


def test_the_same_dry_run_twice_gives_the_same_plan_id(lib):
    first = go(entry(), {"ids": ["a", "b"]}, dry_run=True)["data"]["plan_id"]
    again = go(entry(), {"ids": ["b", "a"]}, dry_run=True)["data"]["plan_id"]
    assert first == again
    assert go(entry(), {"ids": ["a"]}, dry_run=True)["data"]["plan_id"] != first


def test_a_what_if_without_items_makes_no_plan(lib):
    env = go(entry(dry_run="what_if", method="change"), {}, dry_run=True)
    assert env["outcome"] == "ok" and env["data"] == {"limit": 5}
    assert not (lib.support / "plans").exists()


def test_a_dry_run_that_the_entry_does_not_have_is_bad_args(lib):
    env = go(entry(dry_run=None), {"ids": ["a"]}, dry_run=True)
    assert env["outcome"] == "bad_args" and env["reason"] == "usage"


# --- --plan ---

def test_a_run_with_a_plan_runs_its_items_skips_a_changed_one_and_lists_a_new_one(lib):
    plan_id = go(entry(), {"ids": ["a", "b", "c"]}, dry_run=True)["data"]["plan_id"]
    STATE["b"] = "rename"  # b's answer is another now
    env = go(entry(), {"ids": ["a", "b", "d"], "plan_id": plan_id}, yes=True)
    assert env["outcome"] == "ok"
    assert env["data"] == {"ran": ["a"], "skipped": [{"key": "b", "state": "skipped", "reason": "changed"},
                                                     {"key": "c", "state": "skipped", "reason": "changed"}],
                           "new_since_plan": ["d"]}
    assert WRITTEN == [["a"]]


def test_a_run_without_a_plan_plans_fresh(lib):
    env = go(entry(), {"ids": ["a", "b"]}, yes=True)
    assert env["data"] == {"ran": ["a", "b"]} and WRITTEN == [["a", "b"]]


def test_an_unknown_plan_is_bad_args_unknown_id(lib):
    for text in ("plan:0123456789ab", "nonsense", "plan:../x"):
        env = go(entry(), {"ids": ["a"], "plan_id": text}, yes=True)
        assert (env["outcome"], env["reason"]) == ("bad_args", "unknown_id"), text
    assert WRITTEN == []


def test_a_plan_of_another_music_folder_is_refused_expired_with_the_dry_run_as_next(lib):
    other = plan_store.save(lib.support, "demo write", "/somewhere/else", rows(["a"]), {"command": "demo write"})
    env = go(entry(), {"ids": ["a"], "plan_id": other}, yes=True)
    assert (env["outcome"], env["reason"]) == ("refused", "plan_expired")
    assert [n["run"] for n in env["next"]] == ["demo write --dry-run"]
    assert WRITTEN == []


def test_a_plan_older_than_a_day_is_refused_expired(lib):
    old = plan_store.save(lib.support, "demo write", str(lib.root), rows(["a"]), {"command": "demo write"},
                          now=datetime.now() - timedelta(hours=25))
    env = go(entry(), {"ids": ["a"], "plan_id": old}, yes=True)
    assert (env["outcome"], env["reason"]) == ("refused", "plan_expired")
    assert env["next"][0]["run"] == "demo write --dry-run" and WRITTEN == []


# --- --yes ---

def test_a_command_the_window_asks_about_is_refused_without_yes_and_shows_its_dry_run(lib, monkeypatch):
    monkeypatch.setitem(catalog.CONFIRM, "demo write", "Undo these? Their files go back.")
    env = go(entry(needs_yes=True), {"ids": ["a", "b"]})
    assert (env["outcome"], env["reason"]) == ("refused", "needs_yes")
    assert env["message"] == "Undo these? Their files go back."
    assert [r["key"] for r in env["data"]["items"]] == ["a", "b"] and env["data"]["plan_id"].startswith("plan:")
    assert WRITTEN == []  # nothing was done


def test_without_a_row_in_the_table_the_refusal_says_the_reasons_own_words(lib):
    env = go(entry(needs_yes=True), {"ids": ["a"]})
    assert env["reason"] == "needs_yes" and "needs --yes" in env["message"]


def test_a_needs_yes_command_without_a_dry_run_is_refused_with_no_data(lib):
    env = go(entry(needs_yes=True, dry_run=None), {"ids": ["a"]})
    assert (env["outcome"], env["reason"], env["data"]) == ("refused", "needs_yes", None)
    assert WRITTEN == []


def test_yes_runs_it_and_a_dry_run_never_needs_it(lib):
    assert go(entry(needs_yes=True), {"ids": ["a"]}, yes=True)["data"] == {"ran": ["a"]}
    assert WRITTEN == [["a"]]
    assert go(entry(needs_yes=True), {"ids": ["a"]}, dry_run=True)["outcome"] == "ok"
    assert WRITTEN == [["a"]]  # the dry run wrote nothing


def test_a_command_the_window_does_not_ask_about_needs_no_yes(lib):
    assert go(entry(), {"ids": ["a"]})["outcome"] == "ok"
    assert WRITTEN == [["a"]]


def test_call_cannot_get_round_needs_yes(lib, monkeypatch):
    # `call <method>` picks the entry its arguments name and runs it through `run`: the refusal stands
    monkeypatch.setattr(catalog, "by_method", lambda method: [entry(needs_yes=True)] if method == "demo_write" else [])
    env = call.run_method("demo_write", {"ids": ["a"]}, Flags(), api=bind.default())
    assert (env["outcome"], env["reason"]) == ("refused", "needs_yes") and WRITTEN == []
    assert call.run_method("demo_write", {"ids": ["a"]}, Flags(yes=True), api=bind.default())["outcome"] == "ok"
    assert WRITTEN == [["a"]]


# --- as_of and next of a dry run ---

def stamp_scan(paths, stamp: str) -> None:
    with db.connect(paths.db_file) as conn, db.transaction(conn):
        conn.execute("UPDATE watched_folders SET last_scan = ?", (stamp,))


def test_a_dry_run_says_when_the_last_scan_was_and_asks_for_a_scan_when_a_folder_is_newer(lib):
    stamp_scan(lib, "2026-11-01T10:00:00")
    os.utime(lib.library, (datetime(2026, 11, 2).timestamp(),) * 2)  # Library/ changed after that scan
    env = go(entry(), {"ids": ["a"]}, dry_run=True)
    assert env["as_of"]["scanned_at"] == "2026-11-01T10:00:00"
    assert [n["run"] for n in env["next"]] == ["library scan"]
    assert "last scan" in env["next"][0]["why"]


def test_a_dry_run_after_the_scan_has_no_next(lib):
    future = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
    stamp_scan(lib, future)
    env = go(entry(), {"ids": ["a"]}, dry_run=True)
    assert env["as_of"]["scanned_at"] == future and env["next"] == []


def test_a_library_never_scanned_is_asked_to_scan(lib):
    env = go(entry(), {"ids": ["a"]}, dry_run=True)
    assert [n["run"] for n in env["next"]] == ["library scan"] and env["as_of"]["scanned_at"] is None


# --- a dry run writes nothing but its plan (the part of T9 this group can pin) ---

def test_a_dry_run_changes_no_byte_outside_plans_and_cache(lib):
    stamp_scan(lib, "2026-11-01T10:00:00")
    skip = (lib.support / "plans", lib.support / "cache")
    before = tree(lib.root, skip)
    env = go(entry(needs_yes=True), {"ids": ["a", "b"]}, dry_run=True)
    assert env["outcome"] == "ok"
    assert tree(lib.root, skip) == before
    assert [p.name for p in (lib.support / "plans").iterdir()] == [f"{env['data']['plan_id'][5:]}.json"]


# --- read-only opens ---

def data_files(paths) -> list[str]:
    return sorted(p.name for p in paths.data.iterdir())


def test_reads_leave_no_wal_shm_or_new_database_beside_library_db(lib):
    assert not Path(f"{lib.db_file}-wal").exists() and not Path(f"{lib.db_file}-shm").exists()
    files, bytes_before = data_files(lib), lib.db_file.read_bytes()
    api = bind.default()
    api.todo()
    api.freshness()
    api.rekordbox_status()
    library.load_state(lib)
    library.import_left(lib)
    assert data_files(lib) == files
    assert lib.db_file.read_bytes() == bytes_before


def test_a_library_without_library_db_gets_none_from_a_read(tmp_path):
    paths = library.Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir(parents=True)
    library.open_state(paths, read_only=True)
    library.load_state(paths)
    library.import_left(paths)
    assert not paths.db_file.exists() and data_files(paths) == []


def test_a_read_only_open_of_a_database_that_is_not_there_fails_and_makes_none(tmp_path):
    with pytest.raises(library.StateError):
        db.connect(tmp_path / "library.db", read_only=True)
    assert list(tmp_path.iterdir()) == []


def test_a_read_only_connection_cannot_write(lib):
    with db.connect(lib.db_file, read_only=True) as conn:
        db.check(conn)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE stray (x)")
    assert not Path(f"{lib.db_file}-wal").exists() and not Path(f"{lib.db_file}-shm").exists()


def test_a_read_beside_a_writer_sees_what_it_committed_and_leaves_the_writers_files(lib):
    writer = db.connect(lib.db_file)
    try:
        with db.transaction(writer):
            writer.execute("UPDATE watched_folders SET last_scan = '2026-11-03T08:00:00'")
        assert Path(f"{lib.db_file}-wal").exists()
        with db.connect(lib.db_file, read_only=True) as conn:
            assert db.freshness(conn)[0] == "2026-11-03T08:00:00"
        assert Path(f"{lib.db_file}-wal").exists() and Path(f"{lib.db_file}-shm").exists()  # the writer's: left alone
    finally:
        writer.close()
    assert not Path(f"{lib.db_file}-wal").exists() and not Path(f"{lib.db_file}-shm").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_in_a_folder_nobody_can_write_the_read_is_immutable_and_still_works(lib):
    before = lib.db_file.read_bytes()
    lib.data.chmod(0o555)
    try:
        assert library.load_state(lib)["tracks"]
        assert data_files(lib) == [n for n in data_files(lib) if "-wal" not in n and "-shm" not in n]
    finally:
        lib.data.chmod(0o755)
    assert lib.db_file.read_bytes() == before


def test_the_api_reads_open_read_only(lib, monkeypatch):
    opened = []
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda path, **kw: opened.append(kw.get("read_only", False)) or real(path, **kw))
    api = bind.default()
    api.todo()
    api.freshness()
    api.rekordbox_status()
    assert opened and all(opened)


# --- a dry run of the sync stores no scan ---

def library_rows(paths) -> tuple:
    with db.connect(paths.db_file, read_only=True) as conn:
        return (conn.execute("SELECT id, path, size, mtime_ns FROM files ORDER BY id").fetchall(),
                conn.execute("SELECT MAX(last_scan) FROM watched_folders").fetchone()[0])


def test_prepare_in_a_dry_run_stores_no_scan_unless_asked(lib):
    (lib.root / "Library" / "Hard_Bounce" / "New Artist - New Song.aiff").write_bytes(b"new audio")
    before = library_rows(lib)
    log = rep.RunLog(datetime.now())
    state = run_mod._open(lib, log, lambda e: None, dry_run=True, scan=False)
    assert not any("New Artist - New Song" in path for path in state["files"])  # the plan is on the last scan
    assert library_rows(lib) == before
    run_mod._open(lib, log, lambda e: None, dry_run=True, scan=True)  # the window's refresh asks for the scan
    after = library_rows(lib)
    assert any("New Artist - New Song" in row[1] for row in after[0]) and after != before


def test_prepare_decides_the_scan_from_dry_run_unless_told(lib, monkeypatch):
    seen = []
    monkeypatch.setattr(run_mod, "_open", lambda paths, log, emit, *, dry_run, scan: seen.append((dry_run, scan))
                        or library.load_state(paths))
    for kwargs in ({}, {"dry_run": True}, {"dry_run": True, "scan": True}):
        try:
            run_mod.prepare(lib, **kwargs)
        except run_mod.SetupProblem:
            pass  # the playlists cannot be read in a test: the scan decision came first
    assert seen == [(False, True), (True, False), (True, True)]


# --- the dry run of `upgrade apply` (part b): the engine's preview, through the real catalogue rows ---


from discjockey.hub import api as api_module  # noqa: E402

from batch_helpers import make_lib, needs_ffmpeg, use  # noqa: E402
from convert_helpers import EXACT  # noqa: E402
from discjockey import align  # noqa: E402
from discjockey.rekordbox import process  # noqa: E402

KINDS = ["mp3", "stale", "aiff", "mp3_plain"]


def upgrade_row() -> Entry:
    """The catalogue's `upgrade apply` row that answers the command and its `--dry-run`."""
    [row] = [e for e in catalog.ENTRIES if e.method == "upgrade" and e.command == ("upgrade", "apply")]
    assert row.dry_run == "upgrade_preview" and not row.planned
    return row


@pytest.fixture
def upgrades(tmp_path, monkeypatch):
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, text: text)  # the fixture's keys are not real song keys
    lib = make_lib(tmp_path, monkeypatch, KINDS)
    use(lib, monkeypatch)
    monkeypatch.setattr(align, "compare_files", lambda a, b: EXACT)
    return lib


def preview(lib, args: dict | None = None, **flags) -> dict:
    return call.run(upgrade_row(), args if args is not None else {"track_ids": lib.tracks}, Flags(dry_run=True, **flags),
                    api=bind.default())


@needs_ffmpeg
def test_upgrade_apply_all_dry_run_lists_what_upgrade_all_would_run(upgrades):
    lib = upgrades
    api = bind.default()
    group = next(g for g in api.todo("upgrade_ready")["groups"])
    wanted = [i["track_id"] for i in group["items"] if i["same_track"] is None]
    assert lib.tracks[1] not in wanted and len(wanted) == 3  # `stale`: the edit differs, so the person chooses
    env = preview(lib, {}, all=True)
    assert env["outcome"] == "ok", env
    data = env["data"]
    assert [r["key"] for r in data["items"]] == wanted == [lib.tracks[0], lib.tracks[2], lib.tracks[3]]
    assert (data["mode"], data["total"], data["planned"], data["skipped"]) == ("same_track", 3, 3, 0)
    first = data["items"][0]
    root = lib.paths.root
    assert (first["state"], first["action"], first["file"], first["new_file"], first["superseded"]) == (
        "planned", "same_track", str(root / lib.olds[0]), str(root / "Library/A/Artist - Song 0.aiff"),
        str(root / "Superseded/A/Old 0.mp3"))
    assert set(first) == {"key", "action", "state", "reason", "file", "new_file", "superseded"}
    [place] = data["space"]
    assert set(place) == {"drive", "needed", "free", "enough"} and place["needed"] > 0 and place["enough"] is True
    assert data["rekordbox"] == {"state": "ready", "running": False, "needs_rekordbox_closed": False}
    assert env["data"]["plan_id"].startswith("plan:") and env["as_of"]["scanned_at"] is None


@needs_ffmpeg
def test_upgrade_apply_dry_run_of_named_songs_says_why_each_is_skipped(upgrades, monkeypatch):
    lib = upgrades
    monkeypatch.setattr(process, "running", lambda: True)
    env = preview(lib, {"track_ids": [lib.tracks[0], lib.tracks[1], lib.tracks[0]]})
    data = env["data"]
    assert [(r["key"], r["state"], r["reason"]) for r in data["items"]] == [
        (lib.tracks[0], "planned", None), (lib.tracks[1], "skipped", "needs_choice")]  # each song once
    assert data["rekordbox"] == {"state": "ready", "running": True, "needs_rekordbox_closed": True}
    plan = plan_store.load(lib.paths.support, data["plan_id"], str(lib.paths.root))
    assert set(plan.items) == {lib.tracks[0], lib.tracks[1]} and plan.kind == "upgrade apply same_track"
    api = bind.default()
    nobody = api.upgrade_preview(["nope"])
    assert [(r["state"], r["reason"]) for r in nobody["items"]] == [("skipped", "no_upgrade")]


@needs_ffmpeg
def test_upgrade_preview_asks_for_songs_or_all_but_not_both_and_all_is_same_track_only(upgrades):
    api = bind.default()
    answer = api.upgrade_preview()
    assert (answer["ok"], answer["kind"], answer["reason"]) == (False, "bad_args", "usage")
    assert api.upgrade_preview(["", 3])["kind"] == "refused"  # the window's own rule for a list that is no songs
    for kwargs in ({"track_ids": upgrades.tracks, "all": True}, {"all": True, "mode": "new_track"}):
        answer = api.upgrade_preview(**kwargs)
        assert (answer["kind"], answer["reason"]) == ("bad_args", "conflicting_flags"), kwargs
    assert api.upgrade_preview(upgrades.tracks, "swap")["reason"] == "usage"
    assert api.upgrade_preview(upgrades.tracks, all=True, mode="discard")["reason"] == "conflicting_flags"


@needs_ffmpeg
def test_the_new_track_preview_names_the_files_it_would_add(upgrades):
    answer = bind.default().upgrade_preview(upgrades.tracks[:3:2], "new_track")
    assert answer["ok"] and answer["mode"] == "new_track" and answer["planned"] == 2
    assert {r["action"] for r in answer["items"]} == {"add_new"} and all(r["new_file"] for r in answer["items"])
    assert answer["rekordbox"]["needs_rekordbox_closed"] is False  # New track never writes rekordbox


# --- T9: a dry run writes exactly one file, its plan ---

def snapshot(folder: Path, skip: tuple[Path, ...]) -> dict[str, str]:
    return tree(folder, skip)


T9 = {  # command -> (what to run for its `--dry-run`: the arguments and flags)
    "upgrade apply": [({"track_ids": "all-tracks"}, {}), ({}, {"all": True})],
    "upgrade discard": [({"track_ids": "all-tracks"}, {})],
    "track undo": [({"track_ids": "all-tracks"}, {})],
    "batch undo": [({"batch_id": "a-batch"}, {})],
    "rekordbox restore": [({"backup": "a-backup"}, {})],
}


def t9_cases():
    return [(command, args, flags) for command, runs in T9.items() for args, flags in runs]


@needs_ffmpeg
@pytest.mark.parametrize("command,args,flags", t9_cases(), ids=lambda v: str(v) if isinstance(v, str) else "")
def test_t9_a_dry_run_changes_no_byte_outside_plans_and_cache(upgrades, command, args, flags):
    lib = upgrades
    (entry,) = [e for e in catalog.ENTRIES if " ".join(e.command) == command and e.dry_run and e.planned is None]
    args = {k: (lib.tracks if v == "all-tracks" else v) for k, v in args.items()}
    if args.get("batch_id") == "a-batch":  # a batch of the first song, done (what an undo would look at)
        with db.connect(lib.paths.db_file) as conn:
            batch = db.start_aiff_batch(conn, "upgrade", "user", "selection", [(lib.tracks[0], "same_track")],
                                        datetime(2026, 11, 16, 9, 0, 0))
            db.set_aiff_item(conn, batch, 0, "done", None, {})
        args["batch_id"] = f"aiff:{batch}"
    if args.get("backup") == "a-backup":  # a copy of the fixture rekordbox library (what a restore would put back)
        from discjockey.rekordbox import backup as rb_backup
        with rb_backup.master.open_read(lib.place, False) as m:
            dbid = m.dbid
        made = rb_backup.Backup.ensure(lib.paths, lib.place, dbid=dbid, batch_id=None, tracks=[])
        made.close(lib.place)
        args["backup"] = made.id
    support, music, rekordbox = lib.paths.support, lib.paths.root, lib.folder
    skip = (support / "plans", support / "cache")
    before = [snapshot(f, skip) for f in (support, music, rekordbox)]
    assert not (support / "plans").exists()
    env = call.run(entry, args, Flags(dry_run=True, **flags), api=bind.default())
    assert env["outcome"] == "ok", env
    after = [snapshot(f, skip) for f in (support, music, rekordbox)]
    assert after == before  # every byte and every file outside plans/ and cache/, library.db and rekordbox included
    if command in api_module.NO_PLAN_COMMANDS:  # Discard and Undo run on what is there when --yes comes: no plan, no file
        assert "plan_id" not in env["data"] and not (support / "plans").exists()
    else:
        assert [p.name for p in (support / "plans").iterdir()] == [f"{env['data']['plan_id'][5:]}.json"]


def test_t9_covers_every_built_entry_with_a_dry_run():
    """A group that builds a command with a `--dry-run` adds its row to `T9`: until then the command is not covered."""
    built = {" ".join(e.command) for e in catalog.ENTRIES if e.dry_run and e.planned is None and e.command}
    assert built <= set(T9), f"add the dry run of {sorted(built - set(T9))} to T9"
    planned_with_cases = {c for c in T9 if any(" ".join(e.command) == c and e.dry_run for e in catalog.ENTRIES)}
    assert planned_with_cases == set(T9)


def test_a_rekordbox_reader_makes_no_lock_file_and_still_sees_a_writer(tmp_path):
    from discjockey.rekordbox import lock
    with lock.reader_lock(tmp_path) as free:
        assert free is True
    assert list(tmp_path.iterdir()) == []  # a read, and a dry run that is one, writes nothing
    with lock.writer_lock(tmp_path):
        with lock.reader_lock(tmp_path) as free:
            assert free is False
    with lock.reader_lock(tmp_path) as free:
        assert free is True


def test_upgrade_all_with_nothing_parked_is_a_dry_run_of_nothing_on_both_paths(lib):
    """No parked upgrade (the common state): `--all` selects no song, the preview of none answers ok with total 0, and
    `upgrade_preview(all=True)` says the same."""
    api = bind.default()
    for answer in (api.upgrade_preview(all=True), api.upgrade_preview([])):
        assert answer["ok"] and (answer["total"], answer["planned"], answer["items"], answer["space"]) == (0, 0, [], [])
    env = call.run(upgrade_row(), {}, Flags(dry_run=True, all=True), api=api)
    assert env["outcome"] == "ok" and env["data"]["total"] == 0 and "plan_id" in env["data"]
