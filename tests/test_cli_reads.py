"""Group V1.8 (issue 39): the reads `todo list`, `upgrade list`, `check list`, `track show` and `track find`. The parity,
golden and T7' harnesses of every built read are in tests/test_cli_golden.py (they run these entries too, on
`rich_library`); this file pins what is particular to these commands: the person steps of a check, the search, the
cutoff sentence, and the pages' headings."""
import json

import pytest
from hub_helpers import LOSSLESS, LOSSY, choose_music, entry, make_root, services, write, write_state
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import library, words
from discjockey.hub import views
from discjockey.hub.api import CliApi



def rich_library(tmp_path, monkeypatch):
    """The hub fixtures with something on every list: t2 has a better version parked (and waits for rekordbox), t1 has
    an open check on an added file, t4 one on a swap. Rekordbox is closed (conftest) and has no tracks."""
    paths = make_root(tmp_path, upgrade=True)
    state = library.load_state(paths)
    state["tracks"]["t2"]["upgrade"]["auto_waits"] = True
    state["tracks"]["t1"]["rekordbox_check"] = {"reason": "added_as_new", "since": "2026-10-20", "match": "exact",
                                                "aligned": True}
    state["tracks"]["t4"] = entry(artist="Pegassi", title="AEIOU", duration_ms=180000, folder="Hard_Bounce",
                                  path="Library/Hard_Bounce/Pegassi - AEIOU.aiff", status="lossless",
                                  source="qobuz", source_id="q4", source_format="flac",
                                  rekordbox_check={"reason": "swapped", "since": "2026-10-19", "moved": False})
    write(paths, "Library/Hard_Bounce/Pegassi - AEIOU.aiff", b"aiff")
    write_state(paths, state)
    choose_music(tmp_path, monkeypatch)
    make_master(tmp_path / "rekordbox", [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox"))
    return paths


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def rich(tmp_path, monkeypatch):
    return rich_library(tmp_path, monkeypatch)


def data_of(argv, capsys):
    code, out, _ = run([*argv, "--json"], capsys)
    return code, json.loads(out)


# --- person steps (design §10.1) ---

def test_a_new_track_check_gives_relocate_new_with_the_new_absolute_path(rich, capsys):
    _, env = data_of(["check", "list"], capsys)
    item = next(i for g in env["data"]["groups"] for i in g["items"] if i["track_id"] == "t1")
    (step,) = item["check"]["person_steps"]
    assert step["id"] == "step:relocate_new"
    assert step["say"].endswith(f"The new file: {rich.root / LOSSLESS}") and step["then"] == "check done t1"


def test_a_swap_check_gives_reload_tag_and_the_engines_own_sentence(rich, capsys):
    _, env = data_of(["check", "list"], capsys)
    item = next(i for g in env["data"]["groups"] for i in g["items"] if i["track_id"] == "t4")
    (step,) = item["check"]["person_steps"]
    assert step == {"id": "step:reload_tag", "say": item["check"]["text"], "then": "check done t4"}


def test_the_words_helper_covers_same_track_and_convert_and_leaves_a_clean_name_alone():
    usb = {"reason": "repointed", "rekordbox": {"entries": [1]}}
    (same,) = words.person_steps("k", usb)
    assert same["id"] == "step:reload_tag" and same["say"].endswith("Rebuild the stick in rekordbox before your next gig.")
    (convert,) = words.person_steps("k", {"reason": "converted", "rekordbox": {"entries": [1]}})
    assert convert["id"] == "step:reload_tag" and convert["then"] == "check done k"
    assert words.person_steps("k", {"reason": "renamed"}) == [] and words.person_steps("k", None) == []
    assert words.person_steps("k", {"reason": "added_as_new", "match": "different"}, None)[0]["id"] == "step:relocate_new"


# --- the search ---

def test_find_folds_case_and_accents_like_a_person_types(tmp_path, monkeypatch, capsys):
    paths = make_root(tmp_path)
    state = library.load_state(paths)
    state["tracks"]["t5"] = entry(artist="Beyoncé", title="Halo", duration_ms=1, folder="X", status="missing")
    write_state(paths, state)
    choose_music(tmp_path, monkeypatch)
    for typed in (["Beyonce"], ["BEYONCÉ", "halo"], ["yonc"]):
        _, env = data_of(["track", "find", *typed], capsys)
        assert [r["track_id"] for r in env["data"]["rows"]] == ["t5"], typed
    row = env["data"]["rows"][0]
    assert row["path"] is None and row["rel_path"] is None  # a song waiting for its file is found too


def test_find_by_path_finds_the_song_holding_the_file_absolute_or_relative(rich, capsys):
    for typed in (LOSSY, str(rich.root / LOSSY)):
        code, env = data_of(["track", "find", "--path", typed], capsys)
        (row,) = env["data"]["rows"]
        assert code == 0 and row["track_id"] == "t2" and env["data"]["total"] == 1
        assert row["path"] == str(rich.root / LOSSY) and row["rel_path"] == LOSSY
    _, env = data_of(["track", "find", "--path", "Library/Nowhere.aiff"], capsys)
    assert env["outcome"] == "ok" and env["data"]["total"] == 0


def test_find_says_what_to_say_with_no_words_or_path(rich, capsys):
    code, env = data_of(["track", "find"], capsys)
    assert code == 2 and env["outcome"] == "bad_args"


def test_a_search_with_no_hit_is_ok_and_names_sync_read_when_the_read_is_old(rich, capsys):
    code, env = data_of(["track", "find", "nobody"], capsys)
    assert code == 0 and env["outcome"] == "ok" and env["data"] == {"rows": [], "total": 0}
    assert [n["run"] for n in env["next"]] == ["sync read"]  # nothing was ever read
    assert env["as_of"]["read_at"] is None


def test_a_recent_read_after_the_last_playlist_change_needs_no_next(rich, capsys, monkeypatch):
    import os
    from datetime import datetime
    api = CliApi(rich.support, None, services())
    api._attach(rich)
    monkeypatch.setattr(api, "freshness", lambda: {"scanned_at": None, "read_at": "2026-10-20T21:00:00"})
    old = os.stat(rich.playlists_file).st_mtime
    os.utime(rich.playlists_file, (old, datetime(2026, 10, 20, 20, 0).timestamp()))
    assert "next" not in api.find_tracks("nobody")                                   # read 21:00, now 21:47, list changed 20:00
    os.utime(rich.playlists_file, (old, datetime(2026, 10, 20, 21, 30).timestamp()))
    assert api.find_tracks("nobody")["next"][0]["run"] == "sync read"                # the list changed after the read
    os.utime(rich.playlists_file, (old, datetime(2026, 10, 20, 20, 0).timestamp()))
    monkeypatch.setattr(api._svc, "now", lambda: datetime(2026, 10, 22, 21, 47))
    assert api.find_tracks("nobody")["next"][0]["run"] == "sync read"                # read more than a day ago


def test_track_show_takes_a_path_through_resolve(rich, capsys):
    code, by_path = data_of(["track", "show", LOSSY], capsys)
    assert code == 0 and by_path["data"]["track"]["track_id"] == "t2"
    code, nothing = data_of(["track", "show", "Library/Nowhere.aiff"], capsys)
    assert code == 2 and nothing["reason"] == "unknown_id"


def test_a_check_batch_prints_the_id_check_done_takes_and_lists_its_songs(rich, capsys):
    state = library.load_state(rich)
    for key in ("t1", "t4"):
        state["tracks"][key]["rekordbox_check"]["batch"] = 3
    write_state(rich, state)
    code, text, _ = run(["check", "list"], capsys)
    assert code == 0 and "aiff:3" in text and "check done --batch aiff:3" in text and "2 tracks" in text
    assert "batch:" not in text
    ids = [line.split()[0] for line in text.splitlines() if line.split() and line.split()[0] in ("t1", "t4")]
    assert ids == ["t1", "t4"]  # the songs of the batch, each with its own id, in the batch's own table
    _, env = data_of(["check", "list"], capsys)  # the window's key stays in the data; the typed id sits beside it
    (item,) = [i for g in env["data"]["groups"] for i in g["items"] if i.get("batch")]
    assert item["track_id"] == "batch:3" and item["batch"]["aiff_id"] == "aiff:3"


def test_a_well_formed_song_key_the_library_lacks_is_unknown_id_not_changed(rich, capsys):
    code, env = data_of(["track", "show", "qobuz:999"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "unknown_id")
    assert "track find" in env["message"] and "qobuz:999" in env["message"]


# --- the cutoff sentence is the engine's ---

def test_the_payload_carries_the_cutoff_sentence_the_window_words_itself(rich, capsys):
    _, env = data_of(["track", "show", LOSSY], capsys)
    assert env["data"]["track"]["cutoff_hz"] == 16000
    assert env["data"]["track"]["cutoff_text"] == "16.0 kHz · where the highs end · lossless reaches about 22 kHz"
    _, env = data_of(["track", "show", LOSSLESS], capsys)
    assert env["data"]["track"]["cutoff_text"] is None  # a lossless file has no cutoff to show


@pytest.mark.parametrize("e, expected", [
    ({"status": "fake_lossless", "cutoff_hz": 16000, "path": "Library/A/x.wav"},
     "16.0 kHz · where the highs end · a lossy file inside the WAV"),
    ({"status": "fake_lossless", "cutoff_hz": 16000, "path": "Library/A/x.mp3"},
     "16.0 kHz · where the highs end · a lossy file inside a lossless file"),
    ({"status": "not_lossless", "cutoff_hz": None}, "no clear edge in the highs"),
    ({"status": "missing", "cutoff_hz": None}, None),
    ({"status": "not_lossless", "cutoff_hz": 16000, "import_state": "identified"}, None)])
def test_cutoff_text_words_each_case_like_the_window(e, expected):
    assert views.cutoff_text(e) == expected


# --- the pages ---

def test_the_todo_page_places_the_windows_group_names_and_the_waits_mark(rich, capsys):
    code, text, err = run(["todo", "list"], capsys)
    assert code == 0 and err == ""
    for heading in ("Check in rekordbox", "Upgrade ready"):
        assert heading in text
    assert "Waits for rekordbox to be closed" in text  # the payload's own words for auto_waits
    assert "Reload Tag" in text and "t2" in text and "Pegassi" in text
    assert "chips" not in text.lower()


def test_todo_group_filters_to_one_group_and_a_wrong_one_is_bad_args(rich, capsys):
    _, text, _ = run(["todo", "list", "--group", "upgrade_ready"], capsys)
    assert "Upgrade ready" in text and "Check in rekordbox" not in text
    code, out, err = run(["todo", "list", "--group", "nonsense", "--json"], capsys)
    assert code == 2 and json.loads(out)["outcome"] == "bad_args"


def test_upgrade_list_and_check_list_are_the_todo_page_of_one_group(rich, capsys):
    _, up = data_of(["upgrade", "list"], capsys)
    _, ck = data_of(["check", "list"], capsys)
    assert [g["key"] for g in up["data"]["groups"]] == ["upgrade_ready"]
    assert [g["key"] for g in ck["data"]["groups"]] == ["rekordbox_check"]
    assert up["command"] == "upgrade list" and ck["command"] == "check list"


def test_the_hidden_switch_lists_hidden_songs(rich, capsys):
    state = library.load_state(rich)
    state["tracks"]["t3"]["hidden"] = True
    write_state(rich, state)
    _, plain = data_of(["todo", "list"], capsys)
    _, shown = data_of(["todo", "list", "--hidden"], capsys)
    keys = lambda env: {i["track_id"] for g in env["data"]["groups"] for i in g["items"]}
    assert "t3" not in keys(plain) and "t3" in keys(shown)
    _, text, _ = run(["todo", "list", "--hidden"], capsys)
    assert "Hidden" in text


def test_the_track_page_has_the_windows_sections_and_the_cutoff_sentence(rich, capsys):
    code, text, err = run(["track", "show", LOSSY], capsys)
    assert code == 0 and err == ""
    assert text.splitlines()[0] == "Armin Hermann - Get Naughty"
    for heading in ("Rating", "Verdict", "Cutoff", "Current file"):  # the window's panel: the verdict, then the file
        assert heading in text
    assert "16.0 kHz · where the highs end" in text and "YouTube OPUS" in text
    assert "cutoff_hz" not in text and "16000" not in text  # the raw number has words; --verbose brings it back
    _, verbose, _ = run(["track", "show", LOSSY, "--verbose"], capsys)
    assert "16000" in verbose


def test_the_track_page_of_a_song_still_waiting_for_its_file_prints(rich, capsys):
    state = library.load_state(rich)
    state["tracks"]["local:1"] = entry(artist="Own", title="Waiting", duration_ms=1, folder="", status="missing",
                                       in_playlists=False)
    write_state(rich, state)
    code, text, err = run(["track", "show", "local:1"], capsys)
    assert code == 0 and text.splitlines()[0] == "Own - Waiting"


# --- no music folder, and the answers' parity with the bridge ---

@pytest.mark.parametrize("argv", [["todo", "list"], ["upgrade", "list"], ["check", "list"], ["track", "find", "love"],
                                  ["track", "show", "local:1"]], ids=" ".join)
def test_without_a_music_folder_every_read_is_refused_no_library(argv, capsys):
    code, env = data_of(argv, capsys)  # conftest: an empty support folder, so Setup was never done
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")


def test_a_search_with_no_hit_keeps_parity_with_the_bridge_but_for_next(rich, capsys):
    api = CliApi(rich.support, None, services())
    api._attach(rich)
    answer = api.find_tracks(["nobody", "here"])
    _, env = data_of(["track", "find", "nobody", "here"], capsys)
    assert env["data"] == {k: v for k, v in answer.items() if k not in ("ok", "next")}
    assert env["next"] == answer["next"]


def test_every_list_prints_the_ids_a_command_takes_next(rich, capsys):
    _, text, _ = run(["todo", "list"], capsys)
    ids = {"t1", "t2", "t3", "t4"}
    assert all(any(line.startswith(i + " ") for line in text.splitlines()) for i in ids)
    _, found, _ = run(["track", "find", "naughty"], capsys)
    assert any(line.startswith("t2 ") for line in found.splitlines())


# --- `upgrade list` on a library of parked upgrades (ported from the retired console tests of `batch_cmd`) ---

from batch_helpers import make_lib, needs_ffmpeg, use  # noqa: E402
from convert_helpers import EXACT  # noqa: E402
from discjockey import align, db  # noqa: E402
from discjockey.library import load_state, save_state  # noqa: E402
from discjockey.rekordbox import backup as rbbackup  # noqa: E402


def parked_lib(tmp_path, monkeypatch, kinds):
    """A library of songs that each have a parked upgrade of the same edit (`stale`: a different edit), the fixture rekordbox
    holding them, and the real compare of two files answering "the same edit"."""
    found = make_lib(tmp_path, monkeypatch, kinds)
    use(found, monkeypatch)
    monkeypatch.setattr(align, "compare_files", lambda a, b: EXACT)
    return found


def listed(capsys, *argv: str) -> list[dict]:
    """The items `upgrade list` answers, in its one group."""
    code, text, _ = run(["upgrade", "list", *argv, "--json"], capsys)
    env = json.loads(text)
    assert code == 0 and env["outcome"] == "ok"
    return [item for g in env["data"]["groups"] for item in g["items"]]


@needs_ffmpeg
def test_upgrade_list_shows_what_waits_and_why_same_track_cannot_run(tmp_path, monkeypatch, capsys):
    found = parked_lib(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3"])
    state = load_state(found.paths)
    state["tracks"][found.tracks[3]]["hidden"] = True                  # hidden upgrades aren't listed (as in To-do)
    save_state(found.paths, state)
    with db.connect(found.paths.db_file) as conn:
        batches_before = db.aiff_batches(conn)[1]
    before = found.music(), found.dump(), load_state(found.paths)["tracks"], rbbackup.backups(found.paths)
    with library.run_lock(found.paths.lock):                            # a read takes no lock: busy doesn't matter
        items = listed(capsys)
    assert [i["track_id"] for i in items] == found.tracks[:3]
    first, stale, third = items
    assert (first["artist"], first["title"], first["folder"], first["path"]) == ("Artist", "Song 0", "A", found.olds[0])
    assert first["upgrade_ready"] is True and first["same_track"] is None and third["same_track"] is None
    assert (stale["same_track"], stale["detail"]) == ("needs_choice", "Lossless ready · different edit")
    code, out, _ = run(["upgrade", "list"], capsys)
    assert code == 0 and "Artist" in out and "Song 0" in out and "Upgrade ready" in out
    with db.connect(found.paths.db_file) as conn:
        assert db.aiff_batches(conn)[1] == batches_before
    assert (found.music(), found.dump(), load_state(found.paths)["tracks"], rbbackup.backups(found.paths)) == before


@needs_ffmpeg
def test_the_waiting_mark_is_listed_only_while_same_track_can_run(tmp_path, monkeypatch, capsys):
    found = parked_lib(tmp_path, monkeypatch, ["mp3", "stale"])      # the second one is stored as a different edit
    state = load_state(found.paths)
    for key in found.tracks:
        state["tracks"][key]["upgrade"]["auto_waits"] = "2026-11-09T10:00:00"
    save_state(found.paths, state)
    items = listed(capsys)
    assert [(i["same_track"], i["detail"] == "Waits for rekordbox to be closed") for i in items] == [
        (None, True), ("needs_choice", False)]                        # the hub's To-do shows no "waits" over it either
    code, out, _ = run(["upgrade", "list"], capsys)
    assert out.count("Waits for rekordbox to be closed") == 1


@needs_ffmpeg
def test_upgrade_list_shows_the_syncs_refusal_and_the_waiting_mark_while_the_switch_is_on(tmp_path, monkeypatch, capsys):
    from dataclasses import replace

    from discjockey.settings import load_settings, save_settings
    found = parked_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    state = load_state(found.paths)
    record = {"reason": "not_analysed", "message": "rekordbox hasn't analysed this track yet.",
              "at": "2026-11-09T10:00:00", "anlz": {}, "free": None, "files": None}
    state["tracks"][found.tracks[0]]["upgrade"]["auto_refused"] = record
    state["tracks"][found.tracks[1]]["upgrade"]["auto_waits"] = "2026-11-09T10:00:00"
    save_state(found.paths, state)
    first, second, third = listed(capsys)
    assert first["detail"] == "Not analysed in rekordbox · not upgraded at your sync"
    assert second["detail"] == "Waits for rekordbox to be closed" and third["detail"] != second["detail"]
    code, out, _ = run(["upgrade", "list"], capsys)
    assert "Not analysed in rekordbox · not upgraded at your sync" in out
    assert "Waits for rekordbox to be closed" in out
    save_settings(found.paths.settings_file, replace(load_settings(found.paths.settings_file), auto_upgrade=False))
    first, second, third = listed(capsys)                              # switch off: the waiting mark is hidden
    assert second["detail"] != "Waits for rekordbox to be closed"
    assert first["detail"] == "Not analysed in rekordbox · not upgraded at your sync"


@needs_ffmpeg
def test_upgrade_list_with_nothing_waiting(tmp_path, monkeypatch, capsys):
    found = parked_lib(tmp_path, monkeypatch, ["mp3"])
    state = load_state(found.paths)
    state["tracks"][found.tracks[0]]["upgrade"] = None
    save_state(found.paths, state)
    code, text, _ = run(["upgrade", "list", "--json"], capsys)
    env = json.loads(text)
    assert code == 0 and env["outcome"] == "ok" and env["data"]["groups"] == []
    code, out, _ = run(["upgrade", "list"], capsys)
    assert code == 0 and "Upgrade ready" not in out
