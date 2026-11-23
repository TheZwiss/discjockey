"""Issue 39 V4.2b: the commands that change playlists.txt, through the command line, end to end: `playlist add`, `remove`,
`rename`, `move`, `enable`, `disable`, `edit` and `add-liked`. A job's worker runs in this process
(`test_cli_upgrade.inline_workers`). The library is the hub fixture's (`hub_helpers.make_root`: Hard_Bounce and
Powertrance, Powertrance's one song in Hard_Bounce as well) with the playlists read stored (`test_cli_golden.with_read`:
without a read every playlist is unread and no change has files to move). The text pages of `playlist move`,
`playlist rename` and `playlist add-liked` are pinned by `tests/cli_golden/playlist_{move,rename,add_liked}.txt`."""
from __future__ import annotations

import json
import shlex

import pytest
from hub_helpers import ID1, ID2, PLAYLISTS, QOBUZ_LINK, choose_music, make_root
from test_cli_golden import check_golden, golden_page, with_read
from test_cli_upgrade import inline_workers, run, run_json  # noqa: F401 - fixtures
from test_hub_api_playlists import SC_SET

from discjockey import playlist_words, playlists_file as pf, words
from discjockey.cli import parser
from discjockey.hub import catalog
from discjockey.settings import Account, Settings, save_settings

OK, BAD_ARGS, REFUSED = 0, 2, 7
HARD = f"https://open.spotify.com/playlist/{ID1}"
POWER = f"https://open.spotify.com/playlist/{ID2}"
COMMANDS = [e for e in parser.built() if e.method in ("save_playlists", "add_liked_music")]


@pytest.fixture
def lib(tmp_path, monkeypatch, inline_workers):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    with_read(paths, monkeypatch)
    elsewhere = tmp_path / "elsewhere"  # where a person keeps a list of their own: the folder the command runs in
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return paths


def liked_music(paths, on=True) -> None:
    save_settings(paths.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}, read_liked_music=on))


def rows(paths) -> list[tuple[str, str, bool]]:
    return [(r.folder, r.ref, r.enabled) for r in pf.load(paths.playlists_file).rows]


def jobs_of(paths) -> list[str]:
    folder = paths.support / "jobs"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def typed(line: dict) -> list[str]:
    """A `next` line as a person types it after the program's path."""
    return shlex.split(line["run"])[1:]


def line_of(env: dict, *start: str) -> list[str]:
    """The words of the first `next` line that starts with `start` (never "the last line": `library scan` may follow)."""
    found = [typed(n) for n in env["next"] if typed(n)[:len(start)] == list(start)]
    assert found, env["next"]
    return found[0]


def folder_on_disk(paths, name: str) -> bool:
    return (paths.root / "Library" / name).exists()


# --- the examples and the words ---

@pytest.mark.parametrize("entry", COMMANDS, ids=lambda e: " ".join(e.command))
def test_every_example_runs_on_the_fixture(entry, lib, tmp_path, capsys):
    (tmp_path / "elsewhere" / "my-playlists.txt").write_text(f"Powertrance = {POWER}\n")
    liked_music(lib)
    code, env = run_json(shlex.split(entry.example), capsys)
    assert code == OK and env["outcome"] == "ok" and env["command"] == " ".join(entry.command), env


def test_the_nine_commands_are_built_and_the_preview_has_no_command():
    assert {" ".join(e.command) for e in COMMANDS} == {f"playlist {w}" for w in (
        "add", "remove", "rename", "move", "enable", "disable", "edit", "add-liked")}
    assert catalog.entry_of("preview_playlist_change", "").command == ()


@pytest.mark.parametrize("line,message", [
    ("playlist move Powertrance", "--to is missing."),
    ("playlist rename Powertrance", "Say which folder: FOLDER."),
    ("playlist remove", "Say which playlist: PLAYLIST."),
    ("playlist edit", "--file is missing."),
    ("playlist add", "Say which url: URL."),
    ("playlist add x --at x", "--at takes a number, not x."),
])
def test_a_line_that_is_incomplete_says_what_is_missing(line, message, lib, capsys):
    code, env = run_json(shlex.split(line), capsys)
    assert (code, env["outcome"], env["reason"], env["message"]) == (BAD_ARGS, "bad_args", "usage", message)
    assert jobs_of(lib) == []


def test_if_version_with_a_dry_run_is_refused_in_the_words_of_the_rule(lib, capsys):
    code, env = run_json(["playlist", "remove", "Powertrance", "--if-version", "a" * 64, "--dry-run"], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "conflicting_flags")
    assert env["message"] == parser.IF_VERSION_ON_DRY_RUN
    code, env = run_json(["playlist", "remove", "Powertrance", "--files", "move", "--dry-run"], capsys)
    assert code == OK  # --files is fine on a dry run: the preview always lists what it answers


# --- the guided flow: a dry run, the line that makes the change, history and its undo ---

# (the line, what playlists.txt holds before it when not the fixture's, the answer to the save question it needs)
CHANGES = {
    "add": (["playlist", "add", SC_SET, "--folder", "A_set", "--at", "2"], None, None),
    "remove": (["playlist", "remove", "Powertrance"], None, None),
    "rename": (["playlist", "rename", "Hard_Bounce", "Hard_Bounce_2"], None, "move"),
    "move": (["playlist", "move", "Powertrance", "--to", "1"], None, "move"),
    "enable": (["playlist", "enable", "Powertrance"], f"# my playlists\nHard_Bounce = {HARD}\n#off# Powertrance = {POWER}\n", None),
    "disable": (["playlist", "disable", "Powertrance"], None, None),
    "edit": (["playlist", "edit", "--file", "other.txt"], None, "move"),  # the list in the other order
}


def start(lib, tmp_path, op: str):
    """The line of `op` with playlists.txt as it needs it; returns (the line, the answer to the save question)."""
    line, before, files = CHANGES[op]
    if before is not None:
        lib.playlists_file.write_text(before)
    (tmp_path / "elsewhere" / "other.txt").write_text(f"Powertrance = {POWER}\nHard_Bounce = {HARD}\n")
    return line, files


@pytest.mark.parametrize("op", CHANGES)
def test_a_dry_runs_next_line_makes_the_change_and_history_offers_the_line_that_undoes_it(op, lib, tmp_path, capsys):
    line, files = start(lib, tmp_path, op)
    original = rows(lib)
    code, env = run_json([*line, "--dry-run"], capsys)
    assert code == OK and rows(lib) == original and jobs_of(lib) == []
    version = pf.load(lib.playlists_file).version
    if files is None:
        [offered] = [w for w in map(typed, env["next"]) if w[:2] == line[:2]]  # (an add may be told to check its link first)
        assert offered[-2:] == ["--if-version", version]
        assert words.APPLY_WHY in [n["why"] for n in env["next"]]
    else:  # a change that puts files elsewhere: one line for each answer
        both = [w for w in map(typed, env["next"]) if w[:2] == line[:2]]
        assert [w[-2:] for w in both] == [["--files", "move"], ["--files", "leave"]] and both[0][-4:-2] == ["--if-version", version]
        [offered] = both[:1]
    code, env = run_json(offered, capsys)  # run as typed
    assert code == OK and env["outcome"] == "ok", env
    assert rows(lib) != original
    code, env = run_json(["history"], capsys)
    undo = next(e["undo"] for e in env["data"]["entries"] if e["kind"] == "operation")
    assert undo.endswith(f"--if-version {pf.load(lib.playlists_file).version}") and undo.startswith("playlist ")
    code, env = run_json([*shlex.split(undo), *(["--files", files] if files else [])], capsys)  # run as typed
    assert code == OK and env["outcome"] == "ok", env
    assert rows(lib) == original  # the (folder, playlist, on or off) of each row, in order


def test_the_undo_of_a_change_is_refused_after_a_hand_edit_of_the_file(lib, capsys):
    assert run_json(["playlist", "disable", "Powertrance"], capsys)[0] == OK
    undo = next(e["undo"] for e in run_json(["history"], capsys)[1]["data"]["entries"] if e["kind"] == "operation")
    lib.playlists_file.write_text(lib.playlists_file.read_text() + "# a note\n")
    before = lib.playlists_file.read_text()
    code, env = run_json(shlex.split(undo), capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "version_changed")
    assert lib.playlists_file.read_text() == before
    assert [typed(n) for n in env["next"]] == [["playlist", "list"]]


def test_the_undo_of_a_rename_with_its_files_puts_the_file_and_the_folder_back(lib, capsys):
    original = lib.playlists_file.read_bytes()
    assert run_json(["playlist", "rename", "Hard_Bounce", "Hard_Bounce_2", "--files", "move"], capsys)[0] == OK
    assert folder_on_disk(lib, "Hard_Bounce_2") and not folder_on_disk(lib, "Hard_Bounce")
    entries = run_json(["history"], capsys)[1]["data"]["entries"]
    undo = next(e["undo"] for e in entries if e["kind"] == "operation")  # (the batch that moved the files is a line of its own)
    code, env = run_json([*shlex.split(undo), "--files", "move"], capsys)
    assert code == OK
    assert lib.playlists_file.read_bytes() == original
    assert folder_on_disk(lib, "Hard_Bounce") and not folder_on_disk(lib, "Hard_Bounce_2")


# --- the refusals, each before any job ---

def test_a_stale_version_is_refused_with_the_command_that_lists_the_playlists_and_starts_no_job(lib, capsys):
    code, env = run_json(["playlist", "remove", "Powertrance", "--if-version", "a" * 64], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "version_changed")
    assert env["message"] == playlist_words.PLAYLISTS_VERSION_CHANGED
    assert [typed(n) for n in env["next"]] == [["playlist", "list"]]
    assert len(rows(lib)) == 2 and jobs_of(lib) == []


def test_a_version_that_is_none_is_refused_in_its_words(lib, capsys):
    for bad in ("nonsense", "a" * 63, ""):
        code, env = run_json(["playlist", "remove", "Powertrance", "--if-version", bad], capsys)
        assert (code, env["outcome"], env["reason"], env["message"]) == (BAD_ARGS, "bad_args", "usage", words.BAD_PLAYLIST_VERSION)
    assert jobs_of(lib) == []
    version = pf.load(lib.playlists_file).version
    assert run_json(["playlist", "disable", "Powertrance", "--if-version", version.upper()], capsys)[0] == OK  # any case


def test_a_change_that_moves_files_is_refused_without_the_answer_and_says_the_two_lines(lib, capsys):
    before = lib.playlists_file.read_bytes()
    version = pf.load(lib.playlists_file).version
    code, env = run_json(["playlist", "move", "Powertrance", "--to", "1"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_choice")
    assert lib.playlists_file.read_bytes() == before and jobs_of(lib) == []
    base = ["playlist", "move", "Powertrance", "--to", "1", "--if-version", version]
    assert [typed(n) for n in env["next"]] == [[*base, "--files", "move"], [*base, "--files", "leave"]]
    assert [n["why"] for n in env["next"]] == [words.APPLY_MOVE_WHY, words.APPLY_LEAVE_WHY]
    code, env = run_json(typed(env["next"][1]), capsys)  # the second line, as typed: leave the files
    assert code == OK and [r[0] for r in rows(lib)] == ["Powertrance", "Hard_Bounce"]


def test_a_files_answer_that_is_neither_move_nor_leave_is_refused_in_its_words(lib, capsys):
    code, env = run_json(["playlist", "move", "Powertrance", "--to", "1", "--files", "bogus"], capsys)
    assert (code, env["outcome"], env["reason"], env["message"]) == (BAD_ARGS, "bad_args", "usage", "--files is move or leave, not bogus.")
    assert run_json(["playlist", "move", "Powertrance", "--to", "1", "--files", "LEAVE"], capsys)[0] == OK


def test_a_playlist_that_is_not_listed_is_refused_and_starts_no_job(lib, capsys):
    code, env = run_json(["playlist", "remove", "Nope"], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused") and "Nope" in env["message"]
    assert jobs_of(lib) == []


def test_a_relative_file_resolves_against_the_folder_the_command_runs_in_and_a_missing_one_says_so(lib, tmp_path, capsys):
    (tmp_path / "elsewhere" / "list.txt").write_text(f"Hard_Bounce = {HARD}\nPowertrance = {POWER}\nAdded = {SC_SET}\n")
    code, env = run_json(["playlist", "edit", "--file", "list.txt"], capsys)
    assert code == OK and [r[0] for r in rows(lib)] == ["Hard_Bounce", "Powertrance", "Added"]
    code, env = run_json(["playlist", "edit", "--file", "gone.txt"], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused")
    assert env["message"] == playlist_words.PLAYLIST_FILE_MISSING.format(path=str(tmp_path / "elsewhere" / "gone.txt"))
    assert len(jobs_of(lib)) == 1  # only the edit that went through
    code, env = run_json(["playlist", "edit", "--file", ""], capsys)
    assert (code, env["message"]) == (BAD_ARGS, words.LOCAL_PATH_MISSING)


def test_an_add_without_a_folder_needs_the_playlist_read_first_and_says_which_command(lib, capsys):
    code, env = run_json(["playlist", "add", SC_SET], capsys)
    assert (code, env["outcome"], env["message"]) == (BAD_ARGS, "bad_args", playlist_words.PLAYLIST_ADD_NEEDS_FOLDER)
    assert [typed(n) for n in env["next"]] == [["playlist", "check", SC_SET]]
    assert jobs_of(lib) == []
    code, env = run_json(["playlist", "add", f"https://open.spotify.com/playlist/{ID1}", "--folder", "Again"], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused")  # already listed
    code, env = run_json(["playlist", "add", QOBUZ_LINK, "--folder", "Q", "--off"], capsys)
    assert code == OK and rows(lib)[-1][2] is False


# --- add-liked ---

def test_add_liked_adds_the_line_when_the_choice_is_on_and_says_when_it_is_off(lib, capsys):
    liked_music(lib, on=False)
    code, env = run_json(["playlist", "add-liked"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "setting_off")
    assert jobs_of(lib) == [] and len(rows(lib)) == 2  # refused before any job
    liked_music(lib)
    code, env = run_json(["playlist", "add-liked"], capsys)
    assert code == OK and env["data"] == {"folder": "Liked_music"} and rows(lib)[-1][0] == "Liked_music"
    code, env = run_json(["playlist", "add-liked"], capsys)
    assert (code, env["reason"]) == (REFUSED, "exists") and len(jobs_of(lib)) == 1


# --- the window's own call and the call command ---

def test_call_of_the_save_by_a_change_equals_the_noun_verb_dry_run(lib, capsys):
    _, direct = run_json(["playlist", "remove", "Powertrance", "--dry-run"], capsys)
    args = json.dumps({"op": {"op": "remove", "playlist": "Powertrance"}})
    code, called = run_json(["call", "save_playlists", "--args", args, "--dry-run"], capsys)
    assert code == OK and called == direct and called["command"] == "playlist remove"


def test_call_of_the_whole_list_save_picks_no_entry_and_says_which_key_it_needs(lib, capsys):
    code, env = run_json(["call", "save_playlists", "--args", '{"lines": []}'], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "usage")
    assert env["message"] == "save_playlists needs op.op with one of the values it takes."


def test_call_of_the_preview_reads_nothing_on_the_network(lib, capsys):
    args = json.dumps({"op": {"op": "move", "playlist": "Powertrance", "to": 1}})
    code, env = run_json(["call", "preview_playlist_change", "--args", args], capsys)
    assert code == OK and env["data"]["kind"] == "moves"
    code, env = run_json(["call", "preview_playlist_change", "--args", json.dumps({"read_unread": True})], capsys)
    assert (code, env["reason"]) == (BAD_ARGS, "usage")
    assert env["message"] == "preview_playlist_change needs read_unread with one of the values it takes."


# --- help ---

def test_help_names_the_flags_the_playlist_commands_cannot_run_without(lib, capsys):
    code, env = run_json(["help", "playlist", "move"], capsys)
    row = env["data"]["commands"][0]
    assert [a["name"] for a in row["args"]] == ["loaded_version", "files.choice", "op.playlist", "op.to"]
    assert row["required_flags"] == ["--to"] and {a["word"]: a["required"] for a in row["args"]}["--to"] is True
    assert row["usage"] == "playlist move PLAYLIST --to TO [--if-version VERSION] [--files move|leave] [--dry-run]"
    assert row["flag_values"] == {"--to": "TO", "--if-version": "VERSION", "--files": "move|leave"}
    row = run_json(["help", "playlist", "rename"], capsys)[1]["data"]["commands"][0]
    assert row["usage"] == "playlist rename PLAYLIST FOLDER [--if-version VERSION] [--files move|leave] [--dry-run]"
    row = run_json(["help", "playlist", "edit"], capsys)[1]["data"]["commands"][0]
    assert row["usage"] == "playlist edit --file PATH [--if-version VERSION] [--files move|leave] [--dry-run]"


def test_help_says_a_flag_the_all_word_stands_in_for_is_not_required(lib, capsys):
    row = run_json(["help", "upgrade", "apply"], capsys)[1]["data"]["commands"][0]
    assert next(a for a in row["args"] if a["word"] == "--way")["required"] is False


# --- the text pages ---

def test_golden_the_pages_of_a_move_a_rename_and_an_add_liked(lib, tmp_path, capsys):
    from test_cli_golden import WRITES
    assert {"playlist_move", "playlist_rename", "playlist_add_liked"} <= set(WRITES)
    scrub = ((r"plan:[0-9a-f]{12}", "plan:<id>"),)
    code, page, _, _ = golden_page(["playlist", "move", "Powertrance", "--to", "1", "--dry-run"], tmp_path, capsys, also=scrub)
    assert code == OK
    check_golden("playlist_move", page)
    code, page, _, _ = golden_page(["playlist", "rename", "Hard_Bounce", "Hard_Bounce_2", "--files", "move"], tmp_path, capsys, also=scrub)
    assert code == OK
    check_golden("playlist_rename", page)
    liked_music(lib)
    code, page, _, _ = golden_page(["playlist", "add-liked"], tmp_path, capsys, also=scrub)
    assert code == OK
    check_golden("playlist_add_liked", page)
