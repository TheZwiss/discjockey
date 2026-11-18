"""Issue 43 E3b2: the commands for songs whose file is missing, through the command line, end to end (plan §6.2):
`missing list`, `missing download` and `missing remove` with a song, with `--all`, with `--dry-run` and (Remove) with and
without `--yes`; nothing left, skipped songs and the exit codes. A job's worker runs in this process
(`test_cli_upgrade.inline_workers`). The library is `test_missing_actions`' own: t1 a playlist song with its file missing,
t2 one with a parked better version, t4 a song no playlist lists with a parked version, t5 the same with none, t6 one whose
parked record names a file of the user's, t7 a playlist song whose file is there. The text pages are pinned by
`tests/cli_golden/missing_list.txt` (the read) and `missing_download.txt` / `missing_remove.txt`."""
from __future__ import annotations

import re

import pytest
from hub_helpers import choose_music, entry, make_root, write, write_state
from rekordbox_helpers import make_master

from discjockey import db
from discjockey.hub import catalog, ids
from discjockey.library import load_state
from test_cli_upgrade import inline_workers, run, run_json  # noqa: F401 - fixtures

OK, BAD_ARGS, PARTIAL, REFUSED = 0, 2, 6, 7
SINCE = "2026-11-12T09:30:00"
PARKED_OLD = "Upgrades ready/Hard_Bounce/Old Artist - Old Song.aiff"
DECOY = "Library/Hard_Bounce/Decoy - Mine.aiff"
TO_DO_WORDS = "No song whose file is missing waits for"


def song(title, artist, **kw):
    path = kw.pop("path", f"Library/Hard_Bounce/{artist} - {title}.aiff")
    return entry(artist=artist, title=title, duration_ms=180000, folder="Hard_Bounce", path=path, status="lossless",
                 source="qobuz", source_id="q9", source_format="flac", **kw)


def parked(rel):
    return {"file": rel, "source": "qobuz", "source_id": "q2", "source_format": "flac", "found": "2026-10-18",
            "alignment": {"result": "exact", "offset_samples": 0, "offset_ms": 0.0, "drift_ms": 0.0,
                          "text": "matches exactly"}}


def with_missing(paths) -> None:
    """Songs whose file waits as missing, on `make_root(upgrade=True)`'s library (see the module's words)."""
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


def missing_library(tmp_path, monkeypatch):
    """The library of this module's words, chosen as the music folder, rekordbox closed with no tracks (also the golden
    harness's, for the page of `missing list`)."""
    paths = make_root(tmp_path, upgrade=True)
    with_missing(paths)
    choose_music(tmp_path, monkeypatch)
    make_master(tmp_path / "rekordbox", [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox"))
    return paths


@pytest.fixture
def lib(tmp_path, monkeypatch, inline_workers):
    monkeypatch.setattr(ids, "SPOTIFY_ID", re.compile(r"[A-Za-z0-9]{2,22}"))  # t1, t2... pass as song keys
    return missing_library(tmp_path, monkeypatch)


def tracks(paths):
    return load_state(paths)["tracks"]


def tree(paths):
    return sorted(p.relative_to(paths.root).as_posix() for p in paths.root.rglob("*")
                  if p.is_file() and ".discjockey" not in p.parts and ".support" not in p.parts)


def group(env):
    return next(g for g in env["data"]["groups"] if g["key"] == "missing_file")


# --- missing list ---

def test_missing_list_is_the_to_do_group_with_each_songs_action_and_words(lib, capsys):
    code, env = run_json(["missing", "list"], capsys)
    assert code == OK and env["command"] == "missing list" and [g["key"] for g in env["data"]["groups"]] == ["missing_file"]
    g = group(env)
    assert g["all"] == {"download_again": 2, "remove": 3}
    by = {i["track_id"]: i["missing"] for i in g["items"]}
    assert sorted(by) == ["t1", "t2", "t4", "t5", "t6"]
    assert (by["t1"]["action"], by["t1"]["will"]) == ("download_again", "Downloads again at your next sync")
    assert by["t4"]["action"] == "remove" and by["t4"]["upgrade_waiting"] is True


def test_the_text_page_of_missing_list_says_what_each_song_will_get_in_the_engines_words(lib, capsys):
    code, out, err = run(["missing", "list"], capsys)
    assert code == OK and err == ""
    assert "Missing files" in out and "Downloads again at your next sync" in out and "Removed from your library" in out
    assert "download_again" not in out and "{" not in out  # no raw keys or dicts of the nested object


# --- missing download ---

def test_download_again_for_a_song_sets_file_gone_and_changes_nothing_else(lib, capsys):
    before = tree(lib)
    code, env = run_json(["missing", "download", "t1"], capsys)
    assert code == OK and env["outcome"] == "ok" and env["command"] == "missing download" and env["job"], env
    assert env["data"]["action"] == "download_again" and env["data"]["done"] == ["t1"] and env["data"]["skipped"] == []
    assert env["message"] == "1 song downloads again at your next sync."
    [row] = env["data"]["results"]
    assert (row["track_id"], row["state"], row["reason"], row["words"]) == \
           ("t1", "done", None, "Downloads again at your next sync")
    assert tracks(lib)["t1"]["file_gone"] and tree(lib) == before


def test_a_missing_rows_old_path_names_the_song(lib, capsys):
    old = tracks(lib)["t1"]["path"]
    code, env = run_json(["missing", "download", old], capsys)
    assert code == OK and env["data"]["done"] == ["t1"], env


def test_download_again_all_acts_on_the_groups_download_again_songs_only(lib, capsys):
    code, env = run_json(["missing", "download", "--all"], capsys)
    assert code == OK and sorted(env["data"]["done"]) == ["t1", "t2"] and env["data"]["skipped"] == [], env
    assert env["message"] == "1 song downloads again and 1 gets the better version already waiting for it, at your next sync."
    assert not any(tracks(lib)[k].get("file_gone") for k in ("t4", "t5", "t6", "t7"))


def test_download_again_all_with_nothing_left_is_done_and_starts_no_job(lib, capsys):
    run_json(["missing", "download", "--all"], capsys)
    for extra in ([], ["--dry-run"]):
        code, env = run_json(["missing", "download", "--all", *extra], capsys)
        assert (code, env["outcome"], env["job"]) == (OK, "ok", None), env
        assert env["message"] == TO_DO_WORDS + " Download again." and env["data"]["results"] == []


def test_download_again_dry_run_says_per_song_what_would_happen_and_changes_nothing(lib, capsys):
    before, state = tree(lib), tracks(lib)
    code, env = run_json(["missing", "download", "--all", "--dry-run"], capsys)
    assert code == OK and env["outcome"] == "ok" and env["job"] is None, env
    assert env["data"]["action"] == "download_again" and (env["data"]["n"], env["data"]["skipped"]) == (2, 0)
    assert sorted(i["track_id"] for i in env["data"]["items"]) == ["t1", "t2"]
    assert {i["track_id"]: i["upgrade_waiting"] for i in env["data"]["items"]} == {"t1": False, "t2": True}
    assert env["data"]["items"][0]["track_id"] == next(  # the order the group shows them in
        i["track_id"] for i in group(run_json(["missing", "list"], capsys)[1])["items"] if i["track_id"] in ("t1", "t2"))
    assert True and env["message"] == env["data"]["words"]
    assert tree(lib) == before and tracks(lib) == state


def test_a_song_that_gets_the_other_action_is_skipped_and_the_run_is_partial(lib, capsys):
    code, env = run_json(["missing", "download", "t1", "t7", "t4"], capsys)
    assert code == PARTIAL and env["outcome"] == "partial", env
    assert env["data"]["done"] == ["t1"] and env["data"]["skipped"] == ["t7", "t4"]
    rows = {r["track_id"]: r for r in env["data"]["results"]}
    assert (rows["t7"]["reason"], rows["t7"]["words"]) == ("not_missing", "Its file is back.")
    assert rows["t4"]["reason"] == "wrong_action" and rows["t4"]["words"].startswith("This song gets Remove from library")
    assert not tracks(lib)["t4"].get("file_gone")


def test_every_song_skipped_is_refused_and_keeps_the_rows(lib, capsys):
    code, env = run_json(["missing", "download", "t7"], capsys)
    assert code == REFUSED and env["outcome"] == "refused", env
    assert env["data"]["skipped"] == ["t7"] and env["data"]["results"][0]["reason"] == "not_missing"
    code, out, err = run(["missing", "download", "t7"], capsys)
    assert code == REFUSED and "Its file is back." in out + err


def test_download_again_without_songs_is_a_usage_error(lib, capsys):
    code, env = run_json(["missing", "download"], capsys)
    assert code == BAD_ARGS and env["outcome"] == "bad_args"


def test_the_text_page_of_a_download_says_the_line_and_each_songs_words(lib, capsys):
    code, out, err = run(["missing", "download", "t1", "t2"], capsys)
    assert code == OK
    assert out.startswith("1 song downloads again and 1 gets the better version already waiting for it, at your next sync.")
    assert "Downloads again at your next sync" in out and "Gets the better version already waiting" in out


# --- missing remove ---

def test_remove_without_yes_is_refused_with_the_question_and_the_preview_and_removes_nothing(lib, capsys):
    before, state = tree(lib), tracks(lib)
    code, env = run_json(["missing", "remove", "t4"], capsys)
    assert code == REFUSED and (env["outcome"], env["reason"]) == ("refused", "needs_yes"), env
    assert env["message"] == catalog.CONFIRM["missing remove"]
    assert [(i["track_id"], i["will"], i["upgrade_waiting"]) for i in env["data"]["items"]] == [("t4", True, True)]
    assert env["job"] is None and tree(lib) == before and tracks(lib) == state


def test_remove_with_yes_removes_the_song_and_its_parked_download_only(lib, capsys):
    before = tree(lib)
    code, env = run_json(["missing", "remove", "t4", "t5", "--yes"], capsys)
    assert code == OK and env["outcome"] == "ok" and env["data"]["done"] == ["t4", "t5"], env
    assert env["message"] == "Removed 2 songs from your library."
    assert "t4" not in tracks(lib) and "t5" not in tracks(lib) and "t1" in tracks(lib)
    assert [p for p in before if p not in tree(lib)] == [PARKED_OLD]  # no music file: it was missing


def test_remove_all_acts_on_the_groups_remove_songs_only(lib, capsys):
    code, env = run_json(["missing", "remove", "--all", "--yes"], capsys)
    assert code == OK and sorted(env["data"]["done"]) == ["t4", "t5", "t6"], env
    assert DECOY in tree(lib)  # a parked record that names the user's own file leaves that file alone
    assert {"t1", "t2", "t7"} <= set(tracks(lib))
    code, env = run_json(["missing", "remove", "--all", "--yes"], capsys)
    assert (code, env["outcome"], env["job"]) == (OK, "ok", None) and env["message"] == TO_DO_WORDS + " Remove from library."


def test_remove_dry_run_needs_no_yes_and_changes_nothing(lib, capsys):
    before, state = tree(lib), tracks(lib)
    code, env = run_json(["missing", "remove", "--all", "--dry-run"], capsys)
    assert code == OK and env["data"]["action"] == "remove" and env["data"]["n"] == 3, env
    assert env["message"] == "Removes 3 songs from your library.", env
    assert tree(lib) == before and tracks(lib) == state


def test_a_playlist_song_gets_no_remove_and_the_run_is_refused(lib, capsys):
    code, env = run_json(["missing", "remove", "t1", "--yes"], capsys)
    assert code == REFUSED and env["data"]["results"][0]["reason"] == "wrong_action", env
    assert "t1" in tracks(lib)


# --- the catalogue ---

def test_help_json_lists_the_three_commands_with_their_flags(lib, capsys):
    code, env = run_json(["help"], capsys)
    assert code == OK
    text = str(env["data"])
    for command in ("missing list", "missing download", "missing remove"):
        assert command in text
    code, env = run_json(["help", "missing", "remove"], capsys)
    assert code == OK and "--yes" in str(env["data"]) and "--all" in str(env["data"]) and "--dry-run" in str(env["data"])


# --- the text pages ---

def test_golden_the_pages_of_a_download_again_and_a_remove(lib, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    code, out, err = run(["missing", "download", "t1", "t2"], capsys)
    assert code == OK and "missing_download" in WRITES
    check_golden("missing_download", out.replace(str(tmp_path), "<tmp>"))
    code, out, err = run(["missing", "remove", "t4", "t5", "--yes"], capsys)
    assert code == OK and "missing_remove" in WRITES
    check_golden("missing_remove", out.replace(str(tmp_path), "<tmp>"))


def test_track_show_words_a_missing_song_in_the_engines_lines_not_raw_keys(lib, capsys):
    code, out, err = run(["track", "show", "t2"], capsys)
    assert code == OK
    assert "\nMissing\n" in out and "Not seen since 12 Nov. It was in Hard_Bounce." in out
    assert "Gets the better version already waiting for it" in out and "download_again" not in out
    code, out, _ = run(["track", "show", "t7"], capsys)  # a song whose file is there has no such section
    assert code == OK and "\nMissing\n" not in out
    code, out, _ = run(["track", "show", "t2", "--verbose"], capsys)  # `--verbose` adds the raw keys beside the words
    assert "download_again" in out and "Not seen since 12 Nov." in out


def test_a_song_held_back_shows_why_and_is_left_out_of_all(lib, capsys):
    st = load_state(lib)
    st["never"] = {"t1": {}}
    write_state(lib, st)
    code, out, _ = run(["missing", "list"], capsys)
    assert code == OK and "Held back" in out and "You chose Never download for it." in out
    code, env = run_json(["missing", "download", "--all"], capsys)
    assert code == OK and env["data"]["done"] == ["t2"], env
    code, env = run_json(["missing", "download", "t1"], capsys)
    assert code == REFUSED and env["data"]["results"][0]["reason"] == "never"
