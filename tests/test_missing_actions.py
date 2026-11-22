"""Issue 43 E3b: the two actions for a song whose file is missing (`missing.download_again`, `missing.remove`), their dry
run (`missing.preview`) and the hub's `missing_files` job and `missing_files_preview` read (plan §4.2-§4.4, §6.1)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from hub_helpers import entry, fake_spotify, make_api, make_root, refreshed, wait_job, write, write_state

from discjockey import db, missing
from discjockey.hub import shapes
from discjockey.library import load_state

SINCE = "2026-11-12T09:30:00"
NOW = datetime(2026, 11, 18, 10, 0, 0)
PARKED_OLD = "Upgrades ready/Hard_Bounce/Old Artist - Old Song.aiff"
DECOY = "Library/Hard_Bounce/Decoy - Mine.aiff"


def song(title, artist, **kw):
    path = kw.pop("path", f"Library/Hard_Bounce/{artist} - {title}.aiff")
    return entry(artist=artist, title=title, duration_ms=180000, folder="Hard_Bounce", path=path, status="lossless",
                 source="qobuz", source_id="q9", source_format="flac", **kw)


def parked(rel):
    return {"file": rel, "source": "qobuz", "source_id": "q2", "source_format": "flac", "found": "2026-10-18",
            "alignment": {"result": "exact", "offset_samples": 0, "offset_ms": 0.0, "drift_ms": 0.0,
                          "text": "matches exactly"}}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """t1 a playlist song with its file missing, t2 a playlist song with a parked better version (its lossy file
    missing), t4 a song no playlist lists any more with a parked version (Remove), t5 the same with none, t6 one whose
    parked record names a file of the user's, t7 a playlist song whose file is there. Their files are gone from disk
    where the row says missing."""
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path, upgrade=True)
    st = load_state(paths)
    st["tracks"]["t4"] = song("Old Song", "Old Artist", in_playlists=False, upgrade=parked(PARKED_OLD))
    st["tracks"]["t5"] = song("Plain Song", "Plain Artist", in_playlists=False)
    st["tracks"]["t6"] = song("Odd Song", "Odd Artist", in_playlists=False, upgrade=parked(DECOY))
    st["tracks"]["t7"] = song("Here Song", "Here Artist")
    for key in ("t4", "t5", "t6", "t7"):
        write(paths, st["tracks"][key]["path"], b"audio " + key.encode())
    write(paths, PARKED_OLD, b"parked old")
    write(paths, DECOY, b"the user's own file")
    write_state(paths, st)
    gone = [st["tracks"][k]["path"] for k in ("t1", "t2", "t4", "t5", "t6")]
    with db.connect(paths.db_file) as conn:
        for rel in gone:
            conn.execute("UPDATE files SET missing_since = ? WHERE path = ?", (SINCE, rel.removeprefix("Library/")))
        conn.commit()
    for rel in gone:
        (paths.root / rel).unlink()
    api, rec = make_api(paths)
    return api, rec, paths


def tree(paths):
    return sorted(p.relative_to(paths.root).as_posix() for p in paths.root.rglob("*")
                  if p.is_file() and ".discjockey" not in p.parts and ".support" not in p.parts)


def entries(paths):
    return load_state(paths)["tracks"]


def log(paths):
    return [json.loads(line) for line in paths.operations_log.read_text().splitlines()]


def rows(paths):
    """The file rows songs keep (the scan indexes a file nobody's song has, like the decoy, as an unlinked row)."""
    with db.connect(paths.db_file, read_only=True) as conn:
        return conn.execute("SELECT id, song, path, missing_since FROM files WHERE song IS NOT NULL ORDER BY id").fetchall()


# --- Download again (plan §4.2) ---

def test_download_again_sets_file_gone_and_nothing_else(lib):
    api, rec, paths = lib
    before, files, kept = entries(paths), rows(paths), tree(paths)
    f = wait_job(api, rec, api.missing_files(["t1", "t2"], "download_again"))
    assert f.ok and f.kind == "missing_files"
    assert f.result["action"] == "download_again" and f.result["done"] == ["t1", "t2"] and f.result["skipped"] == []
    assert [(r["state"], r["reason"]) for r in f.result["results"]] == [("done", None)] * 2
    assert f.result["results"][0]["words"] == "Downloads again at your next sync"
    assert f.result["results"][1]["words"].startswith("Gets the better version already waiting for it")
    assert f.result["words"] == "1 song downloads again and 1 gets the better version already waiting for it, at your next sync."
    after = entries(paths)
    for key in ("t1", "t2"):
        assert after[key]["file_gone"] == api._svc.now().date().isoformat()
        assert {k: v for k, v in after[key].items() if k != "file_gone"} == \
               {k: v for k, v in before[key].items() if k != "file_gone"}
    assert after["t2"]["upgrade"] == before["t2"]["upgrade"]                    # the parked upgrade stays
    assert rows(paths) == files and tree(paths) == kept                          # the row and every file stay
    for key in ("t3", "t4", "t5", "t6", "t7"):
        assert not after[key].get("file_gone")


def test_download_again_logs_each_song_and_uses_the_hub_clock(lib):
    api, rec, paths = lib
    day = api._svc.now().date().isoformat()
    wait_job(api, rec, api.missing_files(["t1"], "download_again"))
    assert entries(paths)["t1"]["file_gone"] == day
    line = log(paths)[-1]
    assert (line["track_id"], line["operation"], line["result"]) == ("t1", "download again", "done")
    assert line["message"] == "Downloads again at your next sync"


@pytest.mark.parametrize("key,action,reason", [
    ("t7", "download_again", "not_missing"),             # its file is there
    ("t3", "download_again", "not_missing"),             # no file row at all
    ("nope", "download_again", "not_missing"),           # no such song
    ("t4", "download_again", "wrong_action"),            # a song no playlist lists gets Remove
    ("t1", "remove", "wrong_action"),                    # a playlist song gets no Remove
])
def test_a_song_the_action_does_not_fit_is_skipped_with_its_reason_not_switched(lib, key, action, reason):
    api, rec, paths = lib
    before = entries(paths)
    f = wait_job(api, rec, api.missing_files([key, "t5" if action == "remove" else "t1"], action))
    skipped = next(r for r in f.result["results"] if r["track_id"] == key)
    assert (skipped["state"], skipped["reason"]) == ("skipped", reason)
    assert skipped["words"] == missing.reason_words(reason, action)
    assert f.result["skipped"] == [key] and len(f.result["done"]) == 1
    assert entries(paths).get(key) == before.get(key)                           # not switched to the other action either


def test_download_again_twice_and_after_a_change_since_the_click_are_skipped(lib):
    api, rec, paths = lib
    assert wait_job(api, rec, api.missing_files(["t1"], "download_again")).ok
    f = wait_job(api, rec, api.missing_files(["t1", "t2"], "download_again"))
    assert [(r["track_id"], r["state"], r["reason"]) for r in f.result["results"]] == [
        ("t1", "skipped", "asked"), ("t2", "done", None)]
    st = load_state(paths)
    st["never"] = {"t2": {"at": "2026-11-18"}}
    st["tracks"]["t2"]["file_gone"] = None
    write_state(paths, st)
    f = wait_job(api, rec, api.missing_files(["t2"], "download_again"))
    assert (f.ok, f.problem) == (False, "changed")
    assert f.result["results"][0]["reason"] == "never"


def test_a_song_found_in_several_places_is_skipped_for_download_again(lib):
    api, rec, paths = lib
    st = load_state(paths)
    st["ambiguous"] = {"t1": ["Library/Hard_Bounce/Copy a.aiff", "Library/Hard_Bounce/Copy b.aiff"]}
    missing_state = {**st, "version": 2}
    r = missing.download_again(paths, ["t1"], now=lambda: NOW, state=missing_state)
    assert [(x.state, x.reason) for x in r] == [("skipped", "found_twice")]
    assert not entries(paths)["t1"].get("file_gone")


def test_all_songs_skipped_ends_the_job_changed_with_the_results_kept(lib):
    api, rec, paths = lib
    f = wait_job(api, rec, api.missing_files(["t7", "t4"], "download_again"))
    assert (f.ok, f.problem) == (False, "changed")
    assert f.result["done"] == [] and f.result["skipped"] == ["t7", "t4"]
    assert [r["reason"] for r in f.result["results"]] == ["not_missing", "wrong_action"]
    assert f.message == "Nothing to do: 2 songs are skipped."
    assert not any(e.get("file_gone") for e in entries(paths).values())


# --- Remove from library (plan §4.3) ---

def test_remove_deletes_the_song_its_row_and_its_parked_download_and_no_other_file(lib):
    api, rec, paths = lib
    kept = tree(paths)
    f = wait_job(api, rec, api.missing_files(["t4", "t5"], "remove"))
    assert f.ok and f.result["done"] == ["t4", "t5"] and f.result["words"] == "Removed 2 songs from your library."
    assert {r["words"] for r in f.result["results"]} == {"Removed from your library"}
    after = entries(paths)
    assert "t4" not in after and "t5" not in after and {"t1", "t2", "t3", "t6", "t7"} <= set(after)
    assert [r[2] for r in rows(paths) if r[2] in ("Hard_Bounce/Old Artist - Old Song.aiff",
                                                  "Hard_Bounce/Plain Artist - Plain Song.aiff")] == []
    assert tree(paths) == [p for p in kept if p != PARKED_OLD]                  # the parked download, nothing else
    assert (paths.root / DECOY).exists()
    logged = {(line["track_id"], line["operation"]) for line in log(paths)}
    assert {("t4", "removed from library"), ("t5", "removed from library")} <= logged


def test_remove_scans_first_so_a_file_put_back_since_the_last_scan_is_not_forgotten(lib):
    """Issue 43, FA (F6): the mark is only as new as the last scan; the file of t5 came back under another name."""
    api, rec, paths = lib
    st = load_state(paths)
    st["tracks"]["t5"]["upgrade"] = parked(PARKED_OLD)
    write_state(paths, st)
    write(paths, "Library/Hard_Bounce/Plain Artist - Restored.aiff", b"audio t5")  # not scanned yet
    assert entries(paths)["t5"]["missing_since"] == SINCE
    with db.connect(paths.db_file) as conn:
        db.set_decision(conn, "same_song", "t1", "t5", "not_same", NOW)
        conn.commit()
    f = wait_job(api, rec, api.missing_files(["t4", "t5"], "remove"))
    assert f.ok and f.result["done"] == ["t4"] and f.result["skipped"] == ["t5"]
    assert [r["reason"] for r in f.result["results"] if r["track_id"] == "t5"] == ["not_missing"]
    kept = entries(paths)["t5"]
    assert kept["path"] == "Library/Hard_Bounce/Plain Artist - Restored.aiff" and not kept.get("missing_since")
    assert kept["upgrade"] == parked(PARKED_OLD) and "t4" not in entries(paths)
    with db.connect(paths.db_file, read_only=True) as conn:
        assert db.decisions(conn)["same_song"] == [["t1", "t5", "not_same"]]


def test_remove_never_deletes_a_file_that_is_not_discjockeys_parked_download(lib):
    api, rec, paths = lib
    f = wait_job(api, rec, api.missing_files(["t6"], "remove"))
    assert f.ok and "t6" not in entries(paths)
    assert (paths.root / DECOY).read_bytes() == b"the user's own file"             # the record named it; it stays
    assert "left alone" in log(paths)[-1]["message"]


def test_remove_drops_the_answers_naming_the_song(lib):
    api, rec, paths = lib
    st = load_state(paths)
    own = {**song("Own Song", "Own Artist", in_playlists=False), "folder": "Hard_Bounce"}
    st["tracks"]["local:9"] = own
    write(paths, own["path"], b"own audio")
    write_state(paths, st)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ? WHERE path = ?", (SINCE, own["path"].removeprefix("Library/")))
        db.set_decision(conn, "same_song", "t1", "local:9", "not_same", NOW)
        conn.commit()
    (paths.root / own["path"]).unlink()
    f = wait_job(api, rec, api.missing_files(["local:9"], "remove"))
    assert f.ok
    with db.connect(paths.db_file, read_only=True) as conn:
        assert db.decisions(conn)["same_song"] == []


def test_remove_deletes_the_parked_download_only_after_the_records_are_saved(lib, monkeypatch):
    """A save that fails leaves the song, its record of the parked file and the file itself; a crash after the save can
    leave at worst an orphan download, never a record naming a deleted file (plan §4.3)."""
    api, rec, paths = lib
    before, kept = entries(paths), tree(paths)

    def refuse(*a, **kw):
        raise RuntimeError("the save did not commit")
    monkeypatch.setattr(missing.library, "save_state", refuse)
    with pytest.raises(RuntimeError):
        missing.remove(paths, ["t4"], now=lambda: NOW)
    assert (paths.root / PARKED_OLD).exists() and tree(paths) == kept and entries(paths) == before
    monkeypatch.undo()
    seen = []
    real = missing.library.delete_parked
    monkeypatch.setattr(missing.library, "delete_parked", lambda p, rel: seen.append(("t4" in entries(paths), rel)) or real(p, rel))
    assert [r.state for r in missing.remove(paths, ["t4"], now=lambda: NOW)] == ["done"]
    assert seen == [(False, PARKED_OLD)]                                        # the song's record was gone when the file went


def test_remove_is_refused_for_a_song_found_in_several_places(lib):
    # F5 (amended at FB): both copies are there; after Remove they would be unlinked rows the import makes new songs of
    api, rec, paths = lib
    st = load_state(paths)
    st["ambiguous"] = {"t5": ["Library/Hard_Bounce/Copy a.aiff", "Library/Hard_Bounce/Copy b.aiff"]}
    r = missing.remove(paths, ["t5"], now=lambda: NOW, state=st)
    assert [(x.state, x.reason) for x in r] == [("skipped", "found_twice")] and "t5" in entries(paths)


def test_remove_skips_a_song_whose_rekordbox_check_is_open_and_one_that_is_back(lib):
    api, rec, paths = lib
    st = load_state(paths)
    st["tracks"]["t5"]["rekordbox_check"] = {"batch": 1, "reason": "swap"}
    write_state(paths, st)
    f = wait_job(api, rec, api.missing_files(["t5", "t7", "t4"], "remove"))
    assert [(r["track_id"], r["reason"]) for r in f.result["results"]] == [
        ("t5", "check_open"), ("t7", "not_missing"), ("t4", None)]
    assert f.result["words"] == "Removed 1 song from your library; 2 are skipped."
    assert {"t5", "t7"} <= set(entries(paths)) and "t4" not in entries(paths)
    assert (paths.root / PARKED_OLD).exists() is False


def test_nothing_is_removed_without_the_action(lib):
    api, rec, paths = lib
    before, kept, files = entries(paths), tree(paths), rows(paths)
    assert api.missing_files_preview(["t4", "t5"], "remove")["ok"]               # a dry run removes nothing
    assert api.missing_files(["t4"], "delete")["kind"] == "bad_args"             # an unknown word does nothing
    assert api.missing_files([], "remove")["ok"] is False
    wait_job(api, rec, api.rescan_library())                                     # a scan decides nothing about a song
    assert entries(paths).keys() == before.keys() and tree(paths) == kept and rows(paths) == files


# --- the dry run (plan §4.4) ---

def test_the_preview_says_per_song_what_would_happen(lib):
    api, rec, paths = lib
    out = api.missing_files_preview(["t1", "t2", "t4", "t7"], "download_again")
    assert out["ok"] and out["action"] == "download_again" and (out["n"], out["skipped"]) == (2, 2)
    by = {i["track_id"]: i for i in out["items"]}
    assert by["t1"] == {"track_id": "t1", "artist": "Vatoz Locoz", "title": "Gimme Gimme", "place": "Hard_Bounce",
                        "since": "2026-11-12", "will": True, "reason": None, "words": "Downloads again at your next sync",
                        "upgrade_waiting": False}
    assert by["t2"]["upgrade_waiting"] is True and by["t2"]["words"].startswith("Gets the better version")
    assert (by["t4"]["will"], by["t4"]["reason"]) == (False, "wrong_action")
    assert by["t4"]["words"] == "This song gets Remove from library instead."
    assert (by["t7"]["reason"], by["t7"]["since"]) == ("not_missing", None)
    assert out["words"] == ("1 song downloads again and 1 gets the better version already waiting for it, at your next "
                            "sync; 2 are skipped.")
    assert (out["button"], out["confirm"]) == ("Download again · 2", None)         # nothing is lost: nothing is asked
    gen = load_state(paths)["generation"]
    assert load_state(paths)["generation"] == gen and not any(e.get("file_gone") for e in entries(paths).values())


def test_the_preview_of_remove_marks_the_parked_version_it_would_delete(lib):
    api, rec, paths = lib
    out = api.missing_files_preview(["t4", "t5", "t1"], "remove")
    assert (out["n"], out["skipped"]) == (2, 1) and out["words"] == "Removes 2 songs from your library; 1 is skipped."
    assert [(i["track_id"], i["upgrade_waiting"]) for i in out["items"]] == [("t4", True), ("t5", False), ("t1", False)]
    assert out["items"][0]["words"] == "Removed from your library"
    assert out["button"] == "Remove from library · 2…"
    assert out["confirm"] == {"title": "Remove 2 songs from your library?", "body": missing.REMOVE_CONFIRM_BODY,
                              "confirm_label": "Remove", "tone": "danger"}
    assert out["confirm"]["body"].startswith("Their files aren't in your watched folders. Discjockey forgets these songs")


def test_the_confirm_of_one_song_is_singular_and_means_the_same(lib):
    api, rec, paths = lib
    one = api.missing_files_preview(["t4"], "remove")["confirm"]
    assert one["title"] == "Remove from your library?" and one["body"] == missing.REMOVE_CONFIRM_BODY_ONE == (
        "Its file isn't in your watched folders. Discjockey forgets this song, your answers about it and any better "
        "version waiting for it. If the file comes back later, it is added as a new song.")
    assert api.missing_files_preview(["t4", "t5"], "remove")["confirm"]["body"] == missing.REMOVE_CONFIRM_BODY


def test_a_song_on_a_drive_that_is_not_connected_is_skipped_by_both_actions_and_the_preview_says_why(lib, monkeypatch):
    api, rec, paths = lib
    # Remove scans first (FA); the rows are set offline by hand here, which a real scan of a reachable folder would undo
    monkeypatch.setattr("discjockey.library.scan_library", lambda *a, **k: None)
    with db.connect(paths.db_file) as conn:
        for key in ("t1", "t5"):
            conn.execute("UPDATE files SET online = 0 WHERE path = ?",
                         (entries(paths)[key]["path"].removeprefix("Library/"),))
        conn.commit()
    away = "Its drive isn't connected; plug it in to decide."
    for action, key, other in (("download_again", "t1", "t2"), ("remove", "t5", "t4")):
        out = api.missing_files_preview([key, other], action)
        by = {i["track_id"]: i for i in out["items"]}
        assert (by[key]["will"], by[key]["reason"], by[key]["words"]) == (False, "away", away)
        assert by[other]["will"] is True and out["n"] == 1 and out["skipped"] == 1
        f = wait_job(api, rec, api.missing_files([key, other], action))
        skipped = next(r for r in f.result["results"] if r["track_id"] == key)
        assert (skipped["state"], skipped["reason"], skipped["words"]) == ("skipped", "away", away)
        assert f.result["skipped"] == [key] and f.result["done"] == [other]
    assert "t5" in entries(paths) and not entries(paths)["t1"].get("file_gone")      # nothing of the offline songs changed


def test_the_preview_sends_the_button_and_the_confirm_for_the_songs_that_run_only(lib):
    api, rec, paths = lib
    one = api.missing_files_preview(["t4", "t1"], "remove")                         # t1 is a playlist song: skipped
    assert (one["n"], one["button"], one["confirm"]["title"]) == (1, "Remove from library · 1…", "Remove from your library?")
    none = api.missing_files_preview(["t1"], "remove")
    assert (none["n"], none["button"], none["confirm"]) == (0, None, None)
    assert none["words"] == "Nothing to remove: 1 song is skipped."
    assert api.missing_files_preview(["t4"], "download_again")["button"] is None


def test_the_command_lines_question_is_the_windows_body():
    from discjockey.hub import catalog
    assert catalog.CONFIRM["missing remove"].endswith(missing.REMOVE_CONFIRM_BODY)


def test_the_preview_refuses_an_unknown_action_and_an_empty_list(lib):
    api, rec, paths = lib
    bad = api.missing_files_preview(["t1"], "forget")
    assert (bad["ok"], bad["kind"], bad["outcome"]) == (False, "bad_args", "bad_args")
    assert api.missing_files_preview([], "remove")["ok"] is False
    assert api.missing_files_preview("t1", "remove")["ok"] is False


@pytest.mark.parametrize("action,plain,placed,removed,skipped,words", [
    ("download_again", 1, 0, 0, 0, "1 song downloads again at your next sync."),
    ("download_again", 2, 0, 0, 1, "2 songs download again at your next sync; 1 is skipped."),
    ("download_again", 0, 1, 0, 0, "1 song gets the better version already waiting for it at your next sync; nothing is downloaded."),
    ("download_again", 0, 2, 0, 0, "2 songs get the better version already waiting for them at your next sync; nothing is downloaded."),
    ("download_again", 1, 1, 0, 0, "1 song downloads again and 1 gets the better version already waiting for it, at your next sync."),
    ("download_again", 2, 2, 0, 0, "2 songs download again and 2 get the better version already waiting for them, at your next sync."),
    ("download_again", 0, 0, 0, 3, "Nothing to do: 3 songs are skipped."),
    ("remove", 0, 0, 1, 0, "Removes 1 song from your library."),
    ("remove", 0, 0, 3, 2, "Removes 3 songs from your library; 2 are skipped."),
    ("remove", 0, 0, 0, 1, "Nothing to remove: 1 song is skipped."),
])
def test_the_summary_line(action, plain, placed, removed, skipped, words):
    assert missing.summary(action, plain, placed, removed, skipped) == words


# --- the hub: the job, the plan made again ---

def test_the_job_plans_the_sync_again_so_the_download_shows_at_once(lib):
    api, rec, paths = lib
    refreshed(api, rec)
    assert api.sync_preview()["groups"] == [] and api.sync_preview()["counts"]["redownloads"] == 0
    assert wait_job(api, rec, api.missing_files(["t1", "t2"], "download_again")).ok
    after = api.sync_preview()
    assert after["counts"]["redownloads"] == 1
    assert [(g["key"], [a["track_id"] for a in g["actions"]]) for g in after["groups"]] == [("acquire:redownload", ["t1"])]
    # t2 has a parked better version: the planner plans no download for it (D12; the sync's last phase places it, E4b)


# --- the contract: the shapes name what the hub sends ---

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "hub-bridge-contract.md"


def test_the_preview_and_the_result_fit_their_shapes(lib):
    api, rec, paths = lib
    out = api.missing_files_preview(["t1"], "download_again")
    assert shapes.validate({k: v for k, v in out.items() if k != "ok"}, "MissingPreview") == []
    f = wait_job(api, rec, api.missing_files(["t1"], "download_again"))
    assert shapes.validate(f.result, "MissingResult") == []
    assert shapes.validate(f.result["results"][0], "MissingItemResult") == []


def test_the_contract_doc_names_the_methods_their_problems_and_the_result():
    text = " ".join(CONTRACT.read_text(encoding="utf-8").split())
    for word in ("`missing_files_preview(track_ids, action)`", "`missing_files(track_ids, action)`", "`missing_files`",
                 "`bad_args`", "`changed`", "`Upgrades ready/`"):
        assert word in text
