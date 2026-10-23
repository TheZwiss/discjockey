import json
from datetime import datetime

import pytest
from hub_helpers import choose_music

import discjockey.cli as cli
from discjockey import upgrades
from discjockey.align import Alignment
from discjockey.library import Paths, empty_state, load_state, run_lock, save_state
from discjockey.planner import ENTRY_KEYS
from discjockey.upgrades_cmd import run_upgrades

PLAYLISTS = ("Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"
             "Powertrance = https://open.spotify.com/playlist/1DiscjockeyExampleList\n")
EXACT = Alignment("exact", 0, 0.0, 0.0, "matches exactly")
DIFFERENT = Alignment("different", text="doesn't line up: a swap would shift your cue points")
NOW = datetime(2026, 10, 20, 21, 0, 0)


def make_entry(folder, artist, title):
    e = dict.fromkeys(ENTRY_KEYS)
    name = f"{artist} - {title}"
    e.update(aliases=[], artist=artist, title=title, duration_ms=180000, folder=folder,
             path=f"Library/{folder}/not_lossless/{name}.aiff", status="not_lossless", source="youtube_music",
             source_id="y1", source_format="opus", cutoff_hz=20100, rejected_sources=[], in_playlists=True,
             added="2026-10-01T10:00:00", last_attempt="2026-10-01", last_upgrade_check="2026-10-10",
             upgrade={"file": f"Upgrades ready/{folder}/{name}.aiff", "source": "qobuz", "source_id": "q1",
                      "source_format": "flac", "found": "2026-10-10", "alignment": EXACT.to_dict()})
    return e


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Two parked upgrades: one in the second playlist folder (shown last), one in the first."""
    paths = Paths(tmp_path, support=tmp_path / ".support")
    (tmp_path / "playlists.txt").write_text(PLAYLISTS)
    state = empty_state()
    state["tracks"]["t2"] = make_entry("Powertrance", "Aaa", "First by name, second by folder")
    state["tracks"]["t1"] = make_entry("Hard_Bounce", "BΞNZ0", "Bass Is Coming")
    for e in state["tracks"].values():
        for rel, data in ((e["path"], b"old audio"), (e["upgrade"]["file"], b"new audio")):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_bytes(data)
    save_state(paths.state_file, state)
    monkeypatch.setattr(upgrades, "build_staged", lambda parked, staged, n: staged.write_bytes(parked.read_bytes()))
    return paths


def answers(*items):
    it = iter(items)

    def ask(prompt=""):
        a = next(it)
        if isinstance(a, BaseException):
            raise a
        return a
    return ask


def run(paths, *items, compare=lambda cur, new: EXACT, opened=None):
    return run_upgrades(paths, ask=answers(*items), opener=(opened.append if opened is not None else print),
                        compare=compare, now=lambda: NOW)


def report(paths):
    return (paths.reports / "2026-10-20_210000.md").read_text()


def test_nothing_waiting(tmp_path, capsys):
    assert run_upgrades(Paths(tmp_path, support=tmp_path / ".support"), ask=answers()) == 0
    assert "No better versions are waiting." in capsys.readouterr().out
    assert not Paths(tmp_path, support=tmp_path / ".support").reports.exists()


def test_each_upgrade_is_shown_like_the_spec(root, capsys):
    assert run(root, "l", "l") == 0
    out = capsys.readouterr().out
    assert out.startswith("Tip: quit rekordbox before swapping.\n")
    assert ("[Hard_Bounce] BΞNZ0 - Bass Is Coming · lossless version from Qobuz\n"
            "  now:  YouTube Music OPUS · cutoff 20.1 kHz   Library/Hard_Bounce/not_lossless/BΞNZ0 - Bass Is Coming.aiff\n"
            "  new:  Qobuz FLAC · verified lossless         Upgrades ready/Hard_Bounce/BΞNZ0 - Bass Is Coming.aiff\n"
            "  Comparing the two versions... matches exactly. A swap keeps your cue points.\n"
            "  [s] swap  [a] add as new file  [d] discard  [f] show in Finder  [l] later (default)  [q] quit\n"
            ) in out
    assert out.index("[Hard_Bounce]") < out.index("[Powertrance]")  # playlists.txt order, not names
    assert not root.reports.exists()  # nothing changed


def test_swap_add_and_discard(root, capsys):
    assert run(root, "s", "a") == 0
    state = load_state(root.state_file)
    assert state["tracks"]["t1"]["path"] == "Library/Hard_Bounce/BΞNZ0 - Bass Is Coming.aiff"
    assert (root.root / "Superseded/Hard_Bounce/BΞNZ0 - Bass Is Coming (lossy).aiff").read_bytes() == b"old audio"
    assert state["tracks"]["t2"]["path"] == "Library/Powertrance/Aaa - First by name, second by folder.aiff"
    text = report(root)
    assert "## Swapped in the better version (cue points stay) (1)" in text
    assert "## Better version added as a new file (1)" in text
    assert json.loads((root.reports / "2026-10-20_210000.json").read_text())["exit_code"] == 0
    assert root.not_lossless_md.exists()
    assert "Swapped." in capsys.readouterr().out


def test_discard_after_invalid_input_and_finder(root, capsys):
    opened = []
    assert run(root, "x", "f", "d", "", opened=opened) == 0
    out = capsys.readouterr().out
    assert "Please type one of: s, a, d, f, l, q." in out
    assert opened == [root.root / "Upgrades ready/Hard_Bounce/BΞNZ0 - Bass Is Coming.aiff"]
    state = load_state(root.state_file)
    assert state["tracks"]["t1"]["upgrade"] is None and state["tracks"]["t1"]["rejected_sources"] == ["qobuz:q1"]
    assert state["tracks"]["t2"]["upgrade"]  # "" = later
    assert "## Better versions you discarded (1)" in report(root)


def test_quit_leaves_the_rest(root, capsys):
    assert run(root, "q") == 0
    assert "[Powertrance]" not in capsys.readouterr().out


def test_swap_not_offered_when_the_versions_do_not_line_up(root, capsys):
    assert run(root, "s", "l", "l", compare=lambda cur, new: DIFFERENT) == 0
    out = capsys.readouterr().out
    assert "Comparing the two versions... doesn't line up: a swap would shift your cue points. Add it as a new " \
           "file, or discard it." in out
    assert "[s] swap" not in out and "Please type one of: a, d, f, l, q." in out
    assert load_state(root.state_file)["tracks"]["t1"]["status"] == "not_lossless"


def test_ctrl_c_keeps_what_was_done_and_writes_the_report(root, capsys):
    assert run(root, "d", KeyboardInterrupt()) == 130
    assert "Stopped." in capsys.readouterr().out
    assert "## Better versions you discarded (1)" in report(root)
    assert json.loads((root.reports / "2026-10-20_210000.json").read_text())["exit_code"] == 130
    assert load_state(root.state_file)["tracks"]["t1"]["upgrade"] is None


def test_a_failed_step_is_reported_and_exits_1(root, capsys):
    calls = iter([EXACT, DIFFERENT])  # the swap measures again and now finds that they don't line up
    assert run(root, "s", "l", compare=lambda cur, new: next(calls, EXACT)) == 1
    assert "! Not swapped" in capsys.readouterr().out
    assert "## Errors (tried again next run) (1)" in report(root)


def test_parked_file_deleted_by_hand_is_forgotten(root, capsys):
    (root.root / "Upgrades ready/Hard_Bounce/BΞNZ0 - Bass Is Coming.aiff").unlink()
    assert run(root, "l") == 0
    assert "no longer in" in capsys.readouterr().out
    assert load_state(root.state_file)["tracks"]["t1"]["upgrade"] is None
    assert "forgotten" in report(root)


def test_current_file_missing_offers_only_discard(root, capsys):
    (root.root / "Library/Hard_Bounce/not_lossless/BΞNZ0 - Bass Is Coming.aiff").unlink()
    assert run(root, "a", "l", "l") == 0
    out = capsys.readouterr().out
    assert "Run a sync first" in out and "Please type one of: d, f, l, q." in out


def test_interrupted_swap_is_recovered_first(root, capsys):
    state = load_state(root.state_file)
    state["pending"].append({"kind": "swap", "track_id": "t9", "target": "Library/X/gone.aiff",
                             "staged": ".discjockey/.tmp/t9/swap.aiff", "backup": "Superseded/X/gone (lossy).aiff",
                             "old_sha256": "0", "new_sha256": "1", "renames": [], "parked": "Upgrades ready/X/g.aiff",
                             "entry": {"artist": "Gone", "title": "Track"}})
    save_state(root.state_file, state)
    assert run(root, "l", "l") == 1
    assert "Could not finish an interrupted swap for Gone - Track" in capsys.readouterr().out
    assert load_state(root.state_file)["pending"] == []


def test_cli_runs_it_under_the_lock(root, monkeypatch):
    choose_music(root.root, monkeypatch)
    with run_lock(root.lock):
        assert cli.main(["upgrades"]) == 3
    monkeypatch.setattr("builtins.input", answers("l", "l"))
    assert cli.main(["upgrades"]) == 0


def test_ctrl_c_during_a_swap_finishes_it_first(root, monkeypatch, capsys):
    import os
    import signal

    def staged_then_ctrl_c(parked, staged, n):
        staged.write_bytes(parked.read_bytes())
        os.kill(os.getpid(), signal.SIGINT)  # the user presses Ctrl-C while the swap is being prepared

    monkeypatch.setattr(upgrades, "build_staged", staged_then_ctrl_c)
    assert run(root, "s", "l") == 130
    state = load_state(root.state_file)
    assert state["tracks"]["t1"]["status"] == "lossless" and state["pending"] == []
    assert "## Swapped in the better version (cue points stay) (1)" in report(root)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_unexpected_error_is_reported_and_the_next_track_still_comes(root, capsys):
    """E.g. every name for the new file is taken: a plain line, an error in the report, exit 1, no traceback."""
    for stem in ("BΞNZ0 - Bass Is Coming", "BΞNZ0 - Bass Is Coming [t1]"):
        (root.root / f"Library/Hard_Bounce/{stem}.aiff").write_bytes(b"user file")
    assert run(root, "a", "d") == 1
    out = capsys.readouterr().out
    assert "! Could not add it as a new file (FileExistsError: no free file name" in out
    assert "## Errors (tried again next run) (1)" in report(root)
    assert "## Better versions you discarded (1)" in report(root)  # the second track was still offered
    assert load_state(root.state_file)["tracks"]["t1"]["upgrade"]  # nothing changed for the first one


def test_unexpected_error_while_swapping(root, monkeypatch, capsys):
    def broken(parked, staged, n):
        raise OSError("Input/output error")

    monkeypatch.setattr(upgrades, "build_staged", broken)
    assert run(root, "s", "l") == 1
    assert "! Could not swap (OSError: Input/output error)" in capsys.readouterr().out
    assert load_state(root.state_file)["tracks"]["t1"]["status"] == "not_lossless"


def test_unexpected_error_while_comparing(root, capsys):
    def broken(cur, new):
        raise MemoryError()

    assert run(root, "l", compare=broken) == 1
    assert "! Could not compare the two versions (MemoryError" in capsys.readouterr().out


def test_no_keyboard_gives_exit_2(root, monkeypatch):
    def no_input(prompt=""):
        raise EOFError

    choose_music(root.root, monkeypatch)
    monkeypatch.setattr("builtins.input", no_input)
    assert cli.main(["upgrades"]) == 2


def test_add_as_new_says_what_to_do_in_rekordbox(root, capsys):
    assert run(root, "l", "a") == 0
    out = capsys.readouterr().out
    assert ("  In rekordbox: if the track shows as missing, use Auto Relocate; it finds the new file by its name. "
            "Then analyse it again and set the cues again (they belong to the old edit).\n") in out
    assert load_state(root.state_file)["tracks"]["t2"]["rekordbox_check"]["reason"] == "added_as_new"
    assert "## Check in rekordbox (1)" in report(root)
    assert "1 track to check in rekordbox (see the report)" in out


def test_a_256_kbps_version_is_named_with_its_bitrate(root, capsys):
    state = load_state(root.state_file)
    state["tracks"]["t1"]["upgrade"].update(source="youtube_music", source_id="m1", source_format="aac",
                                            status="not_lossless", kbps=256, cutoff_hz=20000)
    save_state(root.state_file, state)
    assert run(root, "l", "l") == 0
    out = capsys.readouterr().out
    assert "[Hard_Bounce] BΞNZ0 - Bass Is Coming · 256 kbps version from YouTube Music\n" in out
    assert "  new:  YouTube Music AAC 256 kbps · cutoff 20.0 kHz   Upgrades ready/Hard_Bounce/" in out
    assert "[Powertrance] Aaa - First by name, second by folder · lossless version from Qobuz\n" in out
