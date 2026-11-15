"""Group V1.9 (issue 39): `batch list`, `batch show` and `report show`. The parity, golden and T7' harnesses of every
built read are in tests/test_cli_golden.py (they run these entries too, on `with_batches`); this file pins what is
particular to them: the typed ids of the two batch kinds, newest first with `total`, the items' paths and rekordbox
part, a bare number refused, and the report ids (`last`, `report:<stamp>`)."""
import json
from datetime import datetime

import pytest
from hub_helpers import choose_music, make_root

import discjockey.cli as cli
from discjockey import db
from discjockey.models import PlannedMove

LISTED = {"id", "kind", "batch", "what", "started_by", "state", "stop_reason", "started", "ended", "total", "done",
          "skipped", "failed", "planned", "undone", "backup", "undone_by"}


def with_batches(paths) -> tuple[int, int]:
    """An AIFF batch (two items: one done with a new file and what was written to rekordbox, one skipped), a stopped
    one after it, and a move batch whose one move was skipped. Returns the ids of the first AIFF batch and the move
    batch. The AIFF batches have ids 1 and 2, the move batch id 1: the typed ids keep them apart."""
    with db.connect(paths.db_file) as conn:
        first = db.start_aiff_batch(conn, "upgrade", "user", None, [("t1", "same_track"), ("t2", "same_track")],
                                    datetime(2026, 11, 10, 9, 0, 0))
        db.set_aiff_item(conn, first, 0, "done", None, {
            "path": "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff", "note": "Upgraded",
            "rekordbox": {"entries": ["4711"], "kept": ["title", "comment"]}})
        db.set_aiff_item(conn, first, 1, "skipped", "needs_choice")
        db.set_aiff_batch(conn, first, state="done", backup="2026-11-10_090001", ended=datetime(2026, 11, 10, 9, 1, 0))
        second = db.start_aiff_batch(conn, "convert", "make_aiff", None, [("t2", "convert")],
                                     datetime(2026, 11, 12, 18, 30, 0))
        db.set_aiff_batch(conn, second, state="stopped", stop_reason="rekordbox_open")
        moved = db.start_batch(conn, started_by="tidy", about=None, undoes=None, now=datetime(2026, 11, 11, 12, 0, 0),
                               moves=[PlannedMove("file", None, "Armin Hermann - Get Naughty",
                                                  "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
                                                  "Library/Hard_Bounce/Armin Hermann - Get Naughty.aiff", None,
                                                  "import", "playlist", skip=("not_found", None))])
        db.close_batch(conn, moved, datetime(2026, 11, 11, 12, 0, 5))
    return first, moved


def with_report(paths, stamp: str = "2026-11-10_110000", tracks: tuple[str, ...] = ("t1", "t2")) -> str:
    """A finished run's report, as `reports/<stamp>.json` keeps it: one downloaded song per track."""
    paths.reports.mkdir(parents=True, exist_ok=True)
    day, clock = stamp.split("_")
    (paths.reports / f"{stamp}.json").write_text(json.dumps({
        "started": f"{day}T{clock[:2]}:{clock[2:4]}:00", "finished": f"{day}T{clock[:2]}:{int(clock[2:4]) + 5:02d}:00",
        "exit_code": 0, "results": [{"section": "new_lossless", "status": "lossless", "track_id": t, "artist": "A",
                                     "title": f"Song {t}", "path": f"Library/Hard_Bounce/A - Song {t}.aiff"} for t in tracks]}))
    return stamp


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def data_of(argv, capsys):
    code = cli.main([*argv, "--json"])
    env = json.loads(capsys.readouterr().out)
    return code, env


def test_batch_list_shows_both_kinds_newest_first_with_typed_ids(lib, capsys):
    with_batches(lib)
    code, env = data_of(["batch", "list"], capsys)
    assert code == 0 and env["outcome"] == "ok"
    rows = env["data"]["batches"]
    assert [r["id"] for r in rows] == ["aiff:2", "moves:1", "aiff:1"]         # by start time, not by number
    assert env["data"]["total"] == 3
    assert all(set(r) == LISTED for r in rows)
    stopped, tidy, upgrade = rows
    assert (stopped["kind"], stopped["state"], stopped["stop_reason"], stopped["planned"], stopped["total"]) == (
        "aiff", "stopped", "rekordbox_open", 1, 1)
    assert (tidy["kind"], tidy["what"], tidy["state"], tidy["skipped"], tidy["done"], tidy["total"]) == (
        "moves", "Tidy-up", "done", 1, 0, 1)
    assert (upgrade["kind"], upgrade["what"], upgrade["started_by"], upgrade["done"], upgrade["skipped"],
            upgrade["total"], upgrade["backup"]) == ("aiff", "upgrade", "user", 1, 1, 2, "2026-11-10_090001")


def test_batch_list_takes_a_kind_and_a_limit_and_counts_every_batch(lib, capsys):
    with_batches(lib)
    code, env = data_of(["batch", "list", "--kind", "moves"], capsys)
    assert [r["id"] for r in env["data"]["batches"]] == ["moves:1"] and env["data"]["total"] == 1
    code, env = data_of(["batch", "list", "--limit", "2"], capsys)
    assert [r["id"] for r in env["data"]["batches"]] == ["aiff:2", "moves:1"] and env["data"]["total"] == 3
    code, env = data_of(["batch", "list", "--kind", "aiff", "--limit", "1"], capsys)
    assert [r["id"] for r in env["data"]["batches"]] == ["aiff:2"] and env["data"]["total"] == 2
    code, env = data_of(["batch", "list", "--kind", "tidy"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "bad_id_kind")
    code, env = data_of(["batch", "list", "--limit", "0"], capsys)          # 0 is all, as the page's --limit 0
    assert code == 0 and len(env["data"]["batches"]) == 3


def test_batch_list_with_no_batches_and_with_no_records_is_an_empty_list(lib, tmp_path, capsys):
    code, env = data_of(["batch", "list"], capsys)
    assert code == 0 and env["data"] == {"batches": [], "total": 0}
    lib.db_file.unlink()
    code, env = data_of(["batch", "list"], capsys)
    assert code == 0 and env["data"] == {"batches": [], "total": 0}


def test_batch_list_text_is_a_table(lib, capsys):
    with_batches(lib)
    assert cli.main(["batch", "list"]) == 0
    out = capsys.readouterr().out
    assert "aiff:1" in out and "moves:1" in out and "Tidy-up" in out and "3 of 3 shown" in out


def test_batch_show_aiff_has_each_items_paths_and_rekordbox_part(lib, capsys):
    first, _ = with_batches(lib)
    code, env = data_of(["batch", "show", f"aiff:{first}"], capsys)
    assert code == 0
    data = env["data"]
    assert (data["id"], data["kind"], data["state"], data["backup"], data["total"]) == (
        "aiff:1", "aiff", "done", "2026-11-10_090001", 2)
    done, skipped = data["results"]
    assert done["path"] == "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff" and done["name"] == "Vatoz Locoz - Gimme Gimme"
    assert done["rekordbox"] == {"entries": ["4711"], "kept": ["title", "comment"]} and done["message"] == "Upgraded"
    assert (skipped["state"], skipped["reason"], skipped["path"], skipped["rekordbox"]) == (
        "skipped", "needs_choice", None, None)


def test_batch_show_moves_shows_the_moves_as_stored(lib, capsys):
    _, moved = with_batches(lib)
    code, env = data_of(["batch", "show", f"moves:{moved}"], capsys)
    assert code == 0
    data = env["data"]
    assert (data["id"], data["kind"], data["what"], data["state"], data["skipped"]) == ("moves:1", "moves", "Tidy-up",
                                                                                         "done", 1)
    (move,) = data["moves"]
    assert move["label"] == "Armin Hermann - Get Naughty" and move["state"] == "skipped" and move["reason"] == "not_found"
    assert move["src"].endswith("not_lossless/Armin Hermann - Get Naughty.aiff") and move["text"]
    assert cli.main(["batch", "show", f"moves:{moved}"]) == 0
    assert "Armin Hermann - Get Naughty" in capsys.readouterr().out


def test_a_bare_number_or_an_unknown_batch_is_bad_args(lib, capsys):
    with_batches(lib)
    code, env = data_of(["batch", "show", "3"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "bad_id_kind")
    assert "aiff:3 or moves:3" in env["message"]
    for typed in ("aiff:99", "moves:99"):
        code, env = data_of(["batch", "show", typed], capsys)
        assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "unknown_id"), typed
    code, env = data_of(["batch", "show", "job:ab12cd34"], capsys)
    assert code == 2 and env["reason"] == "bad_id_kind"


def test_the_batch_commands_need_a_music_folder(tmp_path, capsys):
    for argv in (["batch", "list"], ["batch", "show", "aiff:1"]):
        code, env = data_of(argv, capsys)          # conftest: an empty support folder, no Setup done
        assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library"), argv


def test_report_show_last_is_the_newest_reports_run_detail(lib, capsys):
    with_report(lib, "2026-11-09_100000", ("t1",))
    with_report(lib, "2026-11-10_110000")
    code, last = data_of(["report", "show", "last"], capsys)
    assert code == 0 and last["data"]["run"]["run_id"] == "2026-11-10_110000"
    assert last["data"]["run"]["counts"]["lossless"] == 2
    code, typed = data_of(["report", "show", "report:2026-11-10_110000"], capsys)
    assert typed["data"] == last["data"]
    code, older = data_of(["report", "show", "report:2026-11-09_100000"], capsys)
    assert older["data"]["run"]["run_id"] == "2026-11-09_100000" and older["data"]["run"]["counts"]["lossless"] == 1
    code, bare = data_of(["report", "show", "2026-11-09_100000"], capsys)
    assert bare["data"] == older["data"]


def test_report_show_of_a_run_that_is_not_there_is_refused(lib, capsys):
    code, env = data_of(["report", "show", "last"], capsys)
    assert code == 7 and env["outcome"] == "refused" and "no run report" in env["message"]
    code, env = data_of(["report", "show", "report:2026-01-01_000000"], capsys)
    assert code == 7 and env["outcome"] == "refused"
