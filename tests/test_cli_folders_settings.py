"""Group V1.14, part b (issue 39, design §5.2, §6.1): `folder add`, `folder remove`, `settings show` and `settings set
auto-upgrade` through the command line, on a fixture music folder with the import's slow readers faked
(`hub_helpers.fake_import`). A job's worker runs in this process (`test_cli_upgrade.inline_workers`). The text pages are
pinned by `tests/cli_golden/{folder_add,folder_remove,settings_show,settings_set}.txt`; the dry runs are rows of T9
(`test_cli_dryrun.T9`), the locks rows of T10 (`test_cli_locks.DRIVERS`).

The legacy `settings auto-upgrade [on|off]` (issue 33 stage C) left with this group; its tests moved here (a read, a
change, the other settings kept, a busy support lock, a held library lock, a file that cannot be read, the word's
refusal): `settings show` needs no music folder, `settings set` takes the library lock only while a music folder is
chosen."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import discjockey.cli as cli
from discjockey import db, library
from discjockey.cli import bind, parser
from discjockey.hub import catalog
from discjockey.library import run_lock
from discjockey.settings import Settings, load_settings, save_settings
from hub_helpers import choose_music, fake_import, import_folder, music_root
from test_cli_golden import WRITES, check_golden
from test_cli_locks import fake_locks  # noqa: F401 - fixture
from test_cli_upgrade import inline_workers, run, run_json  # noqa: F401 - fixtures

OK, BAD_ARGS, BUSY, REFUSED = 0, 2, 3, 7


@pytest.fixture
def music(tmp_path, monkeypatch, inline_workers):
    """A music folder with the Library's three songs, a folder of three audio files beside it, the import's readers
    faked: `(paths, folder)`."""
    paths = music_root(tmp_path)
    choose_music(paths.root, monkeypatch)
    fake_import(monkeypatch)
    return paths, import_folder(tmp_path, 3)


def watched(paths):
    with db.connect(paths.db_file, read_only=True) as conn:
        return [(f.kind, f.path) for f in db.watched_folders(conn)]


def add(folder, capsys):
    code, env = run_json(["folder", "add", str(folder)], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    return env


# --- folder add ---

def test_folder_add_watches_the_folder_and_imports_it_in_the_same_job(music, capsys):
    paths, folder = music
    env = add(folder, capsys)
    assert env["command"] == "folder add" and env["job"]
    assert env["data"]["files"] == 3 and env["data"]["own_songs"] == 3 and env["data"]["left"] == 0
    assert env["message"] == "Imported 3 files."
    assert ("import", folder) in watched(paths)
    titles = sorted(e["title"] for k, e in library.load_state(paths)["tracks"].items() if k.startswith("local:"))
    assert titles == ["Song 1", "Song 2", "Song 3"]


def test_folder_add_with_a_dry_run_says_whether_the_folder_can_be_watched_and_changes_nothing(music, capsys):
    paths, folder = music
    code, env = run_json(["folder", "add", str(folder), "--dry-run"], capsys)
    assert (code, env["outcome"], env["data"]["usable"], env["data"]["problem"]) == (OK, "ok", True, None)
    assert [k for k, _ in watched(paths)] == ["library"]  # nothing was watched
    assert sorted(p.name for p in folder.iterdir()) == [f"Example Artist - Song {i}.aiff" for i in (1, 2, 3)]
    code, env = run_json(["folder", "add", str(paths.library / "Hard_Bounce"), "--dry-run"], capsys)
    assert (code, env["data"]["usable"]) == (OK, False)  # a folder inside the music folder is watched already
    assert env["message"] == env["data"]["message"] == "This is inside your music folder, which Discjockey watches already."


def test_folder_add_dry_run_of_a_parent_of_a_watched_folder_says_what_it_would_take_over(music, capsys):
    paths, folder = music
    add(folder, capsys)
    code, env = run_json(["folder", "add", str(folder.parent), "--dry-run"], capsys)
    assert (code, env["outcome"], env["data"]["usable"]) == (OK, "ok", True)
    assert env["data"]["merge_hints"] == ["Music is inside it and becomes part of it."]
    assert env["message"] == "Music is inside it and becomes part of it."


def test_folder_add_of_a_folder_that_cannot_be_watched_is_refused_in_the_windows_words(music, capsys):
    paths, folder = music
    code, env = run_json(["folder", "add", str(folder / "nope")], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "refused")
    assert env["message"] == "That folder isn't there. If it is on a drive, connect the drive first."
    assert [k for k, _ in watched(paths)] == ["library"]


def test_folder_add_while_it_is_already_watched_is_refused(music, capsys):
    paths, folder = music
    add(folder, capsys)
    code, env = run_json(["folder", "add", str(folder)], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused")
    assert [k for k, _ in watched(paths)].count("import") == 1


# --- folder remove ---

def test_folder_remove_without_yes_is_needs_yes_with_the_removal_preview_in_data(music, capsys):
    paths, folder = music
    add(folder, capsys)
    code, env = run_json(["folder", "remove", str(folder)], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_yes")
    assert env["data"] == {"name": "Music", "files": 3, "redownload": 0}
    assert env["message"].startswith("Stop watching this folder?")
    assert ("import", folder) in watched(paths)  # nothing was changed


def test_folder_remove_dry_run_is_the_preview_in_the_windows_words(music, capsys):
    paths, folder = music
    add(folder, capsys)
    for word in (str(folder), f"folder:{folder}"):
        code, env = run_json(["folder", "remove", word, "--dry-run"], capsys)
        assert (code, env["outcome"], env["data"]) == (OK, "ok", {"name": "Music", "files": 3, "redownload": 0}), word
        assert env["message"] == "Discjockey forgets its 3 files. The files stay where they are."
    assert ("import", folder) in watched(paths)


def test_folder_remove_with_yes_stops_watching_and_leaves_the_files_where_they_are(music, capsys):
    paths, folder = music
    add(folder, capsys)
    code, env = run_json(["folder", "remove", str(folder), "--yes"], capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "folder remove"), env
    assert env["data"] == {"name": "Music", "files": 3, "redownload": 0}
    assert env["message"] == "Stopped watching Music. Discjockey forgets its 3 files. The files stay where they are."
    assert [k for k, _ in watched(paths)] == ["library"]
    assert sorted(p.name for p in folder.iterdir()) == [f"Example Artist - Song {i}.aiff" for i in (1, 2, 3)]
    assert not [k for k in library.load_state(paths)["tracks"] if k.startswith("local:")]


def test_a_path_that_is_not_watched_is_bad_args_unknown_id_for_both_forms(music, capsys, tmp_path):
    paths, folder = music
    for argv in (["folder", "remove", str(folder)], ["folder", "remove", str(folder), "--dry-run"],
                 ["folder", "remove", str(folder), "--yes"], ["folder", "remove", f"folder:{folder}", "--yes"]):
        code, env = run_json(argv, capsys)  # not watched yet
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id"), argv
        assert str(folder) in env["message"] and "not one of the watched folders" in env["message"]
    add(folder, capsys)
    code, env = run_json(["folder", "remove", str(paths.library), "--yes"], capsys)  # the Library is always watched
    assert (code, env["reason"]) == (BAD_ARGS, "unknown_id") and "Library" in env["message"]
    assert ("import", folder) in watched(paths)


def test_resolve_folder_takes_the_path_in_any_spelling_and_answers_the_folder_id(music, capsys):
    paths, folder = music
    add(folder, capsys)
    api = bind.default()
    [fid] = [r["id"] for r in api.watched_folders()["folders"] if r["kind"] == "import"]
    for word in (str(folder), f"folder:{folder}", f"folder: {folder}/", str(folder).upper()):
        assert api.resolve("folder", [word]) == {"ok": True, "kind": "folder", "resolved": [fid]}, word
    for word, reason in (("", "usage"), ("folder:", "usage"), ("nowhere", "unknown_id")):
        answer = api.resolve("folder", [word])
        assert (answer["ok"], answer["kind"], answer["reason"]) == (False, "bad_args", reason), word


def test_resolve_folder_without_a_music_folder_is_no_library(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    answer = bind.default().resolve("folder", [str(tmp_path)])
    assert (answer["ok"], answer["outcome"], answer["reason"]) == (False, "refused", "no_library")


# --- settings show ---

def test_settings_show_needs_no_music_folder_and_says_what_settings_holds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))  # Setup never done
    code, env = run_json(["settings", "show"], capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "settings show"), env
    data = env["data"]
    assert data["music_folder"] is None and data["auto_upgrade"] is True and data["read_liked_music"] is False
    assert data["accounts"] == {} and data["labels"]["auto_upgrade"] == "Upgrade automatically when I sync"
    assert not (tmp_path / "support" / "settings.json").exists()  # a read writes nothing


def test_settings_show_with_a_music_folder_and_a_login_names_them_in_the_windows_words(music, capsys):
    paths, _ = music
    from discjockey.settings import Account
    save_settings(paths.settings_file, replace(Settings(), daily_qobuz_limit=40, auto_upgrade=False, read_liked_music=True,
                                               accounts={"youtube": Account("chrome", 30)}))
    code, env = run_json(["settings", "show"], capsys)
    data = env["data"]
    assert (code, data["music_folder"], data["auto_upgrade"], data["daily_qobuz_limit"]) == (OK, str(paths.root), False, 40)
    assert data["read_liked_music"] is True  # on, and a YouTube login to read it with
    assert data["accounts"]["youtube"] == {"browser": "chrome", "browser_name": "Chrome", "profile": None,
                                           "profile_name": None, "daily_limit": 30, "extra": None, "last_check": None,
                                           "liked_only": False}


def test_settings_show_holds_the_whole_file_the_checks_the_extras_and_the_seen_warnings(music, capsys):
    paths, _ = music
    from discjockey.settings import Account
    check = {"ok": False, "problem": "no_premium", "kbps": None, "at": "2026-11-01T10:00:00"}
    save_settings(paths.settings_file, replace(
        Settings(), extra_date="2026-11-02", extra_amount=25, qobuz_last_check={"ok": True, "problem": None, "kbps": 1411,
                                                                                "at": "2026-11-01T09:00:00"},
        warnings_seen={"qobuz": "2026-11-01T08:00:00"},
        accounts={"youtube": Account("chrome", 30, "2026-11-02", 5, None, check, True)}))
    code, env = run_json(["settings", "show"], capsys)
    data = env["data"]
    assert code == OK and data["extra"] == {"date": "2026-11-02", "amount": 25}
    assert data["qobuz_last_check"] == {"ok": True, "problem": None, "kbps": 1411, "at": "2026-11-01T09:00:00"}
    assert data["warnings_seen"] == {"qobuz": "2026-11-01T08:00:00"}
    youtube = data["accounts"]["youtube"]
    assert (youtube["extra"], youtube["last_check"], youtube["liked_only"]) == (
        {"date": "2026-11-02", "amount": 5}, check, True)


def test_settings_show_reads_without_the_library_lock_even_while_another_run_holds_it(music, capsys):
    paths, _ = music
    with run_lock(paths.lock):
        code, env = run_json(["settings", "show"], capsys)
    assert (code, env["outcome"], env["data"]["auto_upgrade"]) == (OK, "ok", True)


def test_a_settings_file_that_cannot_be_read_is_config_invalid_for_show_and_set_and_stays_as_it_was(music, capsys):
    paths, _ = music
    paths.settings_file.write_text('{"auto_upgrade": "yes"}')
    code, env = run_json(["settings", "show"], capsys)
    assert (code, env["outcome"], env["reason"]) == (1, "failed", "config_invalid")
    assert "auto_upgrade must be true or false" in env["message"]
    code, env = run_json(["settings", "set", "auto-upgrade", "off"], capsys)
    assert (code, env["reason"]) == (1, "config_invalid") and "yes" in paths.settings_file.read_text()


# --- settings set ---

def test_settings_set_changes_the_switch_the_window_shows_and_says_it(music, capsys):
    paths, _ = music
    code, env = run_json(["settings", "set", "auto-upgrade", "off"], capsys)
    assert (code, env["outcome"], env["command"], env["data"]) == (OK, "ok", "settings set auto-upgrade",
                                                                   {"auto_upgrade": False}), env
    assert env["message"] == "Upgrade automatically when I sync: off. The upgrades that are ready wait in your to-do list."
    assert load_settings(paths.settings_file).auto_upgrade is False
    assert run_json(["settings", "show"], capsys)[1]["data"]["auto_upgrade"] is False
    code, env = run_json(["settings", "set", "auto-upgrade", "on"], capsys)
    assert (code, env["data"]) == (OK, {"auto_upgrade": True})
    assert env["message"] == "Upgrade automatically when I sync: on. Nothing moves until the next sync."
    assert load_settings(paths.settings_file).auto_upgrade is True


def test_settings_set_keeps_the_other_settings(music, capsys):
    paths, _ = music
    save_settings(paths.settings_file, replace(Settings(), daily_qobuz_limit=40, qobuz_skipped=True))
    assert run_json(["settings", "set", "auto-upgrade", "off"], capsys)[0] == OK
    s = load_settings(paths.settings_file)
    assert (s.auto_upgrade, s.daily_qobuz_limit, s.qobuz_skipped) == (False, 40, True)


def test_settings_set_works_without_a_music_folder(tmp_path, monkeypatch, capsys, inline_workers):
    support = tmp_path / "support"
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(support))
    code, env = run_json(["settings", "set", "auto-upgrade", "off"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert load_settings(support / "settings.json").auto_upgrade is False


def test_settings_set_takes_the_support_lock_and_the_library_lock_and_show_takes_none(music, capsys, fake_locks):
    fake_locks.words.clear()
    assert run_json(["settings", "set", "auto-upgrade", "off"], capsys)[0] == OK
    assert {"library", "support"} <= set(fake_locks.words)
    fake_locks.words.clear()
    assert run_json(["settings", "show"], capsys)[0] == OK
    assert fake_locks.words == []


def test_a_library_lock_held_by_another_run_makes_set_busy_and_changes_nothing(music, capsys):
    paths, _ = music
    with run_lock(paths.lock):
        code, env = run_json(["settings", "set", "auto-upgrade", "off"], capsys)
    assert (code, env["outcome"]) == (BUSY, "busy"), env
    assert not paths.settings_file.exists()
    assert run_json(["settings", "set", "auto-upgrade", "off"], capsys)[0] == OK  # free again


def test_a_busy_support_lock_is_a_busy_answer_in_plain_words_not_a_traceback(music, capsys, monkeypatch):
    """Another process saving its own settings for over 2 seconds (a flock of another descriptor conflicts here too)."""
    paths, _ = music
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    with library.support_lock(paths.support):
        code, env = run_json(["settings", "set", "auto-upgrade", "off"], capsys)
    assert (code, env["outcome"]) == (BUSY, "busy"), env
    assert "Another Discjockey process" in env["message"] and "Traceback" not in json.dumps(env)
    assert not paths.settings_file.exists()


def test_the_value_is_on_or_off_only_and_the_old_word_says_what_to_say_instead(music, capsys):
    for argv in (["settings", "set", "auto-upgrade", "maybe"], ["settings", "set", "auto-upgrade"],
                 ["settings", "auto-upgrade"], ["settings", "auto-upgrade", "off"], ["settings"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "usage"), argv
    code, env = run_json(["settings", "auto-upgrade", "off"], capsys)
    assert "say `settings set auto-upgrade on|off`" in env["message"]
    assert not music[0].settings_file.exists()


# --- the catalogue and the pages ---

def test_the_commands_are_built_with_their_locks_and_their_dry_runs():
    by = {" ".join(e.command): e for e in catalog.ENTRIES if e.command and e.planned is None and e.kind != "R"}
    assert by["folder add"].dry_run == "check_import_folder" and by["folder add"].locks == {"library"}
    assert by["folder remove"].needs_yes and by["folder remove"].dry_run == "removal_preview"
    assert by["settings set auto-upgrade"].locks == {"library", "support"}
    assert "settings show" in {" ".join(e.command) for e in parser.built()}
    assert catalog.entry_of("settings_view", "settings show").locks == frozenset()


def test_the_pages_of_the_four_commands_are_the_golden_text(music, capsys, tmp_path):
    paths, folder = music
    assert {"folder_add", "folder_remove", "settings_set"} <= set(WRITES)

    def page(argv):
        code, out, _ = run(argv, capsys)
        assert code == OK
        return out.replace(str(tmp_path), "<tmp>")

    check_golden("folder_add", page(["folder", "add", str(folder)]))
    check_golden("folder_remove", page(["folder", "remove", str(folder), "--yes"]))
    check_golden("settings_set", page(["settings", "set", "auto-upgrade", "off"]))
