"""Convert and Give it its clean name items in AIFF batches (discjockey/batches.py; plan stage D §1.6, §5 D4): the
batch's kind, one session and one backup, per-item skips and answers that changed, Stop and Resume, rekordbox open,
batch undo across kinds (a Convert→Rename chain included), "checked" and the words. Every library and rekordbox library
is built in tmp_path (tests/batch_helpers.py `make_own_lib`)."""
from __future__ import annotations

import pytest

from batch_helpers import Lib, make_own_lib, needs_ffmpeg
from convert_helpers import NOW, never
from discjockey import audio, batches, convert, db, rbstep, rename, report
from discjockey.events import CancelToken
from discjockey.library import load_state, save_state
from discjockey.rekordbox import backup as rbbackup
from discjockey.rekordbox import session as rbsession
from discjockey.rekordbox.eligible import REASONS

pytestmark = needs_ffmpeg

CLEAN = "Library/A/Artist - Song {i}.aiff"


def final(lib: Lib, i: int) -> str:
    """Where song i's file ends: its clean name, in not_lossless/ for a lossy file that was converted (the record's
    status stays)."""
    return (CLEAN.replace("A/", "A/not_lossless/") if lib.olds[i].endswith(".mp3") else CLEAN).format(i=i)


def start(lib: Lib, actions: list[tuple[int, str]], started_by="user", scope=None) -> int:
    return batches.start(lib.paths, [(lib.tracks[i], action) for i, action in actions], started_by=started_by,
                         scope=scope, now=lambda: NOW)


def go(lib: Lib, batch_id: int, *, resume=False, running=never, events=None, token=None):
    fn = batches.resume if resume else batches.run
    return fn(lib.paths, batch_id, emit=(events.append if events is not None else (lambda e: None)), token=token,
              now=lambda: NOW, running=running, place=lib.place)


def states(lib: Lib, batch_id: int) -> list[str]:
    return [i.state for i in lib.batch(batch_id).items]


def undo(lib: Lib, target, **kw):
    return batches.undo(lib.paths, target, running=never, place=lib.place, now=lambda: NOW, **kw)


def only_state(lib: Lib, track: int) -> dict:
    return load_state(lib.paths)["tracks"][lib.tracks[track]]


# --- the kind ---

@pytest.mark.parametrize("actions, kind", [(["convert"], "convert"), (["rename"], "convert"),
                                           (["convert", "rename"], "convert"), (["same_track"], "upgrade"),
                                           (["same_track", "convert"], "mixed"),
                                           (["rename", "same_track", "convert"], "mixed")])
def test_the_kind_of_a_batch_follows_its_actions(tmp_path, monkeypatch, actions, kind):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3"] * len(actions))
    batch_id = start(lib, list(enumerate(actions)))
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_batch(conn, batch_id).kind == kind
    assert [i.action for i in lib.batch(batch_id).items] == actions


def test_make_all_and_cdj_starters_and_scopes_are_stored(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    first = start(lib, [(0, "convert")], started_by="make_aiff", scope="library:all")
    second = start(lib, [(1, "rename")], started_by="cdj_all", scope="todo:cdj")
    assert [(b.kind, b.started_by, b.scope) for b in map(lib.batch, (first, second))] == [
        ("convert", "make_aiff", "library:all"), ("convert", "cdj_all", "todo:cdj")]
    with pytest.raises(ValueError):
        start(lib, [(0, "swap")])


# --- a whole batch ---

def test_a_batch_of_converts_and_renames_uses_one_session_and_one_backup(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "mp3_free", "clean_free"])
    opened = []
    real = rbsession.Session.open.__func__
    monkeypatch.setattr(rbsession.Session, "open", classmethod(
        lambda cls, *a, **k: (opened.append(1), real(cls, *a, **k))[1]))
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert"), (3, "rename")])
    events = []
    result = go(lib, batch_id, events=events)
    assert len(opened) == 1                                     # one session: one rekordbox.lock, one read open
    assert (result.state, result.total, result.done, result.skipped, result.failed) == ("done", 4, 4, 0, 0)
    [only] = rbbackup.backups(lib.paths)                        # one backup for all, named by the batch
    assert result.backup == only.id == lib.batch(batch_id).backup and batch_id in only.batches
    for i in range(4):
        new = final(lib, i)
        assert lib.entry(i)["path"] == new and result.results[i].path == new and (lib.paths.root / new).is_file()
        assert audio.file_facts(lib.paths.root / new).sample_rate == 44100
    assert not (lib.paths.root / "Library/A/Messy 1.aiff").exists()
    assert (lib.paths.root / "Superseded/A/Old 0.mp3").is_file()
    assert [lib.row(i)["FolderPath"] for i in (0, 1)] == [str(lib.paths.root / final(lib, i)) for i in (0, 1)]
    assert [r.rekordbox for r in result.results] == [{"entries": ["1"], "kept": []}, {"entries": ["2"], "kept": []},
                                                     None, None]
    assert [lib.entry(i)["rekordbox_check"]["reason"] for i in range(4)] == ["converted", "renamed", "converted",
                                                                               "renamed"]
    assert [lib.entry(i)["rekordbox_check"]["batch"] for i in range(4)] == [batch_id] * 4
    assert [(e.done, e.total, e.track_id) for e in events] == [(0, 4, lib.tracks[0]), (1, 4, lib.tracks[1]),
                                                               (2, 4, lib.tracks[2]), (3, 4, lib.tracks[3]),
                                                               (4, 4, None)]
    log = lib.paths.operations_log.read_text()
    assert log.count('"operation": "aiff_convert"') == 2 and log.count('"operation": "aiff_rename"') == 2
    assert "upgrade_same_track" not in log and log.count('"result": "done"') == 4
    assert lib.paths.not_lossless_md.exists()


def test_a_batch_of_files_rekordbox_does_not_have_runs_while_rekordbox_is_open(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3_free", "clean_free"])
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    result = go(lib, batch_id, running=lambda: True)
    assert (result.state, result.done) == ("done", 2) and lib.entry(0)["path"] == final(lib, 0)
    assert lib.entry(1)["path"] == final(lib, 1) and rbbackup.backups(lib.paths) == []


def test_rekordbox_open_at_the_start_with_one_file_in_rekordbox_changes_nothing(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3_free", "clean_free", "clean"])
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "rename")])
    db_before, music_before = lib.dump(), lib.music()
    with pytest.raises(batches.RekordboxOpen) as opened:
        go(lib, batch_id, running=lambda: True)
    assert str(opened.value) == convert.REKORDBOX_OPEN
    assert (opened.value.result.state, opened.value.result.stop_reason) == ("stopped", "rekordbox_open")
    assert states(lib, batch_id) == ["planned"] * 3
    assert lib.dump() == db_before and lib.music() == music_before and rbbackup.backups(lib.paths) == []
    done = go(lib, batch_id, resume=True)                       # rekordbox quit: Resume does it all
    assert (done.state, done.done) == ("done", 3)


def test_a_convert_or_rename_item_needs_a_write_when_its_file_is_in_rekordbox(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "mp3_free", "clean", "clean_free"])
    state = load_state(lib.paths)
    needs = lambda *items: batches._needs_write(lib.paths, state, [(lib.tracks[i], a) for i, a in items])  # noqa: E731
    with rbsession.Session.open(lib.paths, place=lib.place, running=never, items_need_write=lambda v: False) as s:
        view = s.view()
        assert needs((0, "convert"))(view) and needs((2, "rename"))(view)           # any format, in rekordbox
        assert not needs((1, "convert"), (3, "rename"))(view)                        # rekordbox doesn't have them
        assert needs((1, "convert"), (3, "rename"), (0, "convert"))(view)           # one is enough
    # with the library unreadable while rekordbox runs (no view) every item with a file counts
    assert needs((1, "convert"))(None) and needs((3, "rename"))(None)
    assert not batches._needs_write(lib.paths, state, [("unknown", "rename")])(None)


def test_the_chain_is_one_item_with_its_final_result(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["chain"])
    batch_id = start(lib, [(0, "convert")])
    result = go(lib, batch_id)
    [item] = result.results
    assert (result.done, item.state, item.action, item.path) == (1, "done", "convert", final(lib, 0))
    assert not any("Song 0 [" in p for p in lib.music())        # no file with the song's ID name is left
    facts = audio.file_facts(lib.paths.root / final(lib, 0))
    assert (facts.bits, facts.sample_rate) == (16, 44100)
    check = lib.entry(0)["rekordbox_check"]
    assert check["reason"] == "converted" and check["batch"] == batch_id
    assert len(lib.paths.operations_log.read_text().splitlines()) == 1


# --- skips and failures go on ---

def test_a_skipped_item_goes_on(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "named", "clean"])
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "rename")])
    music = lib.music()
    result = go(lib, batch_id)
    assert (result.state, result.done, result.skipped, result.failed) == ("done", 2, 1, 0)
    skipped = result.results[1]
    assert (skipped.state, skipped.reason, skipped.message) == ("skipped", "named_already",
                                                                "A clean AIFF with its clean name already.")
    assert states(lib, batch_id) == ["done", "skipped", "done"]
    assert lib.music()[lib.olds[1]] == music[lib.olds[1]]       # the named one is untouched
    assert '"result": "named_already"' in lib.paths.operations_log.read_text()


def test_an_item_whose_answer_changed_is_skipped_with_the_new_reason_never_switched(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["clean", "mp3"])
    # a Convert planned for a file that is a clean AIFF now; a Rename planned for a file that isn't one
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    music = lib.music()
    with pytest.raises(batches.Refused) as refused:
        go(lib, batch_id)
    result = refused.value.result
    assert [(i.state, i.reason) for i in result.results] == [("skipped", "clean_aiff"), ("skipped", "needs_convert")]
    assert result.results[0].message == "This file is a clean AIFF already: Give it its clean name."
    assert result.results[1].message == rbstep.CONVERT_REFUSED["needs_convert"]
    assert str(refused.value) == batches.NOTHING_FILE_ELIGIBLE and "upgrade" not in str(refused.value)
    assert lib.music() == music and lib.entry(0)["path"] == lib.olds[0]            # nothing switched, nothing moved
    assert lib.entry(1)["path"] == lib.olds[1] and rbbackup.backups(lib.paths) == []
    assert "rekordbox_check" not in lib.entry(0) or not lib.entry(0)["rekordbox_check"]


def test_a_library_rekordbox_cant_read_says_the_files_own_words_never_new_track_or_upgrade(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    music = lib.music()
    with pytest.raises(batches.Refused) as refused:
        go(lib, batch_id)
    convert_item, rename_item = refused.value.result.results
    assert (convert_item.reason, convert_item.message) == ("rekordbox_unreadable",
                                                           rbstep.OWN_FILE_REFUSED["rekordbox_unreadable"])
    assert rename_item.reason == "rename_blocked" and "rekordbox's library can't be opened" in rename_item.message
    for item in refused.value.result.results:
        assert "New track" not in item.message and "upgrade" not in item.message.lower()
    assert lib.music() == music and rbbackup.backups(lib.paths) == []


@pytest.mark.parametrize("change, action, reason, words", [
    ({"source": "qobuz"}, "convert", "downloaded", rbstep.CONVERT_REFUSED["downloaded"]),
    ({"artist": ""}, "convert", "no_name", rbstep.CONVERT_REFUSED["no_name"]),
    ({"upgrade": {"file": "Upgrades ready/x.aiff", "alignment": {"result": "exact"}}}, "convert", "upgrade_waits",
     "A better version is waiting: Same track makes it an AIFF."),
    ({"upgrade": {"file": "Upgrades ready/x.aiff", "alignment": {"result": "exact"}}}, "rename", "upgrade_waits",
     "A better version is waiting: Same track makes it an AIFF."),
])
def test_what_the_record_says_now_decides_the_item(tmp_path, monkeypatch, change, action, reason, words):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3" if action == "convert" else "clean", "mp3_free"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[0]].update(change)
    save_state(lib.paths, state)
    batch_id = start(lib, [(0, action), (1, "convert")])
    result = go(lib, batch_id)
    assert (result.done, result.skipped) == (1, 1)
    assert (result.results[0].state, result.results[0].reason, result.results[0].message) == ("skipped", reason, words)
    assert lib.entry(0)["path"] == lib.olds[0]


def test_a_missing_file_and_a_file_that_cannot_be_read_go_on(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "mp3_free", "mp3_free"])
    (lib.paths.root / lib.olds[0]).unlink()
    (lib.paths.root / lib.olds[1]).write_bytes(b"not audio at all")
    batch_id = start(lib, [(0, "convert"), (1, "convert"), (2, "convert")])
    result = go(lib, batch_id)
    assert [i.state for i in result.results] == ["skipped", "failed", "done"]
    assert result.results[0].reason == "file_missing" and result.results[0].message == \
        rbstep.CONVERT_REFUSED["file_missing"]
    assert "couldn't read" in result.results[1].message and "Nothing was changed" in result.results[1].message
    assert lib.entry(1)["path"] == lib.olds[1]


def test_a_surprise_in_one_step_fails_that_item_with_words_for_its_action(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3_free", "clean_free", "mp3_free"])

    def boom(*a, **k):
        raise RuntimeError("the disk")

    monkeypatch.setattr(rename, "rename_file", boom)
    real = convert.convert_file
    monkeypatch.setattr(convert, "convert_file", lambda *a, **k: boom() if a[2] == lib.tracks[0] else real(*a, **k))
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert")])
    result = go(lib, batch_id)
    assert [i.state for i in result.results] == ["failed", "failed", "done"]
    assert result.results[0].message.startswith("Could not convert Artist – Song 0 (RuntimeError: the disk)")
    assert result.results[1].message.startswith("Could not give Artist – Song 1 its clean name (RuntimeError")
    assert not any("upgrade" in i.message for i in result.results[:2])


# --- Stop and Resume ---

def test_stop_between_items_then_resume_asks_again(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "mp3_free"])
    token = CancelToken()
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert")])

    def emit(event):
        if event.track_id == lib.tracks[0]:
            token.cancel()                      # Stop while the first item is in work: it finishes, the next doesn't

    with pytest.raises(batches.Stopped) as stopped:
        batches.run(lib.paths, batch_id, emit=emit, token=token, now=lambda: NOW, running=never, place=lib.place)
    result = stopped.value.result
    assert (result.state, result.stop_reason, result.done) == ("stopped", "stop", 1)
    assert states(lib, batch_id) == ["done", "planned", "planned"]
    assert lib.entry(1)["path"] == lib.olds[1]
    first = lib.entry(0)
    # meanwhile the user's song turns out to be a download: Resume asks again and leaves that one alone
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[1]]["source"] = "qobuz"
    save_state(lib.paths, state)
    done = go(lib, batch_id, resume=True)
    assert (done.state, done.done, done.skipped) == ("done", 2, 1)
    assert [i.state for i in done.results] == ["done", "skipped", "done"] and done.results[1].reason == "downloaded"
    assert lib.entry(0) == first and lib.entry(1)["path"] == lib.olds[1]
    assert lib.entry(2)["path"] == final(lib, 2)


def test_rekordbox_opening_while_a_rename_is_in_work_rolls_it_back_and_stops(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "mp3_free"])
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert")])
    on = {"v": False}

    def emit(event):
        if event.done == 1 and event.track_id:  # the second item begins: rekordbox is opened under it
            on["v"] = True

    with pytest.raises(batches.RekordboxOpen) as opened:
        batches.run(lib.paths, batch_id, emit=emit, now=lambda: NOW, running=lambda: on["v"], place=lib.place)
    assert opened.value.result.stop_reason == "rekordbox_open"
    assert states(lib, batch_id) == ["done", "planned", "planned"]
    assert lib.entry(1)["path"] == lib.olds[1] and (lib.paths.root / lib.olds[1]).is_file()
    assert lib.row(1)["FolderPath"] == str(lib.paths.root / lib.olds[1])
    assert str(opened.value) == batches.STOPPED_BY_REKORDBOX.format(done=1, total=3)


# --- undo ---

def test_batch_undo_goes_newest_first_across_kinds_chain_item_included(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "chain", "mp3_free"])
    originals = lib.music()
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert"), (3, "convert")])
    go(lib, batch_id)
    assert lib.music() != originals
    events = []
    result = undo(lib, batch_id, emit=events.append)
    assert [(r.track, r.state) for r in result.results] == [(t, "undone") for t in reversed(lib.tracks)]
    assert (result.batch, result.total, result.undone, result.refused, result.failed) == (batch_id, 4, 4, 0, 0)
    assert states(lib, batch_id) == ["undone"] * 4
    assert lib.music() == originals                      # every file back where and as it was, the chain's too
    assert [lib.entry(i)["path"] for i in range(4)] == lib.olds
    assert [lib.row(i)["FolderPath"] for i in range(3)] == [str(lib.paths.root / p) for p in lib.olds[:3]]
    assert all(not lib.entry(i)["rekordbox_check"] for i in range(4))
    assert [(e.done, e.total) for e in events] == [(n, 4) for n in range(5)]
    log = lib.paths.operations_log.read_text()
    assert (log.count('"operation": "undo_convert"'), log.count('"operation": "undo_rename"')) == (3, 2)   # a chain's two undos log twice
    assert "upgrade" not in " ".join(r.message for r in result.results).lower()


def test_undo_of_a_list_goes_newest_first_by_the_log_across_kinds(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "mp3_free"])
    batch_id = start(lib, [(2, "convert"), (0, "convert"), (1, "rename")])      # the order they run in
    go(lib, batch_id)
    result = undo(lib, list(lib.tracks))
    assert [r.track for r in result.results] == [lib.tracks[1], lib.tracks[0], lib.tracks[2]]
    assert all(r.state == "undone" for r in result.results)


def test_the_second_undo_of_a_chain_refused_leaves_the_first_standing(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["chain"])
    batch_id = start(lib, [(0, "convert")])
    go(lib, batch_id)
    state = load_state(lib.paths)
    inner = state["tracks"][lib.tracks[0]]["rekordbox_check"]["undo"]["before"]["rekordbox_check"]["undo"]
    (lib.paths.root / inner["old"]).write_bytes(b"the user changed it")   # the convert's own undo is refused (changed)
    result = undo(lib, batch_id)
    [item] = result.results
    assert (item.state, result.undone, result.refused) == ("refused", 0, 1)
    assert item.message.startswith("The clean name is back, but the conversion could not be undone")
    assert states(lib, batch_id) == ["done"]               # it can still be undone later
    assert lib.entry(0)["rekordbox_check"]["reason"] == "converted"
    log = lib.paths.operations_log.read_text()          # the half that happened is in the log, the other is not
    assert log.count('"operation": "undo_rename"') == 1 and '"operation": "undo_convert"' not in log


def test_undo_with_rekordbox_open_at_the_start_changes_nothing(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    go(lib, batch_id)
    db_before, music = lib.dump(), lib.music()
    with pytest.raises(batches.RekordboxOpen) as opened:
        batches.undo(lib.paths, batch_id, running=lambda: True, place=lib.place)
    assert [r.state for r in opened.value.result.results] == ["waiting", "waiting"]
    assert lib.dump() == db_before and lib.music() == music and states(lib, batch_id) == ["done", "done"]


def test_undo_of_files_rekordbox_does_not_have_runs_while_rekordbox_is_open(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3_free", "clean_free"])
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    go(lib, batch_id)
    result = batches.undo(lib.paths, batch_id, running=lambda: True, place=lib.place)
    assert (result.undone, result.refused) == (2, 0) and [lib.entry(i)["path"] for i in range(2)] == lib.olds


def test_a_relocated_convert_is_refused_with_conversion_words_the_others_go_on(tmp_path, monkeypatch):
    from rekordbox_helpers import KEYS, _open
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    go(lib, batch_id)
    con = _open(lib.place.db, KEYS[0])
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID IN ('1', '2')")
    con.commit()
    con.close()
    result = undo(lib, batch_id)
    assert [(r.state, r.reason) for r in result.results] == [("refused", "relocated"), ("refused", "relocated")]
    assert [r.track for r in result.results] == [lib.tracks[1], lib.tracks[0]]
    assert "since it got its clean name" in result.results[0].message           # the rename's words
    assert "since the conversion" in result.results[1].message                  # the Convert's words
    assert not any(w in " ".join(r.message for r in result.results).lower() for w in ("upgrade", "replace"))


# --- checked ---

def test_checked_over_a_batch_clears_the_converted_and_renamed_checks(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean", "chain"])
    batch_id = start(lib, [(0, "convert"), (1, "rename"), (2, "convert")])
    go(lib, batch_id)
    held = [lib.entry(0)["rekordbox_check"]["undo"].get("held")]
    done = batches.checked(lib.paths, batches.tracks_of(lib.paths, batch_id), now=lambda: NOW)
    assert [r.track_id for r in done] == lib.tracks and all(r.section == "rekordbox_checked" for r in done)
    assert all(lib.entry(i)["rekordbox_check"] is None for i in range(3))
    assert not any(h and (lib.paths.root / h).exists() for h in held)
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_backups_in_use(conn) == set()
    again = batches.undo(lib.paths, [lib.tracks[0]], running=never, place=lib.place)
    assert again.results[0].state == "refused"                          # "checked" ended the undo
    assert batches.checked(lib.paths, lib.tracks) == []


def test_checked_batch_through_the_command_line(tmp_path, monkeypatch, capsys):
    from batch_helpers import use
    from discjockey import cli
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    use(lib, monkeypatch)
    batch_id = start(lib, [(0, "convert"), (1, "rename")])
    go(lib, batch_id)
    assert cli.main(["rekordbox", "checked", "--batch", str(batch_id), "--json"]) == 0
    assert all(lib.entry(i)["rekordbox_check"] is None for i in range(2))


# --- words ---

FILE_REASONS = [*rbstep.CONVERT_REFUSED, "rename_blocked", "rekordbox_unreadable", "cloud", "timing", "not_analysed",
                "unclean", "changed", "space", "rekordbox_open", "busy", "later_batch", "not_reached"]


@pytest.mark.parametrize("action", ["convert", "rename"])
@pytest.mark.parametrize("reason", FILE_REASONS)
def test_every_reason_a_file_item_is_skipped_with_has_words_without_upgrade(action, reason):
    assert reason in REASONS
    words = batches.words(reason, action)
    assert words[0].isupper() or words.startswith("rekordbox")           # a sentence; rekordbox in lower case
    assert not words.startswith("Rekordbox") and "upgrade" not in words.lower() and "new track" not in words.lower()
    assert reason == "upgrade_waits" or "same track" not in words.lower()


def test_the_words_of_the_plan_for_the_reasons_a_file_item_meets():
    assert batches.words("upgrade_waits", "convert") == "A better version is waiting: Same track makes it an AIFF."
    assert batches.words("named_already", "rename") == "A clean AIFF with its clean name already."
    # two cases, two sentences: a file with only its name left, and a file with nothing left to do
    assert batches.words("clean_aiff", "convert") == "This file is a clean AIFF already: Give it its clean name."
    assert rbstep.CONVERT_REFUSED["clean_aiff"] != rbstep.CONVERT_REFUSED["named_already"]
    assert batches.words("needs_convert", "rename") == rbstep.CONVERT_REFUSED["needs_convert"]
    assert batches.words("rename_blocked", "rename", why=rename.BLOCKED_WHY["cloud"]) == \
        rbstep.REFUSED["rename_blocked"].format(reason="the track is in Cloud Library Sync")
    assert "can't open this rekordbox version's library" in batches.words("rekordbox_unreadable", "convert")
    # Same track's words are as they were
    assert batches.words("rekordbox_unreadable") == "Same track needs a rekordbox library Discjockey can open. " \
                                                     "Nothing was changed."
    assert batches.words("away") == "Its drive isn't connected. Nothing was changed."


def test_the_usb_step_is_for_a_converted_file_with_rekordbox_tracks_only():
    entries = {"entries": ["1"], "kept": []}
    assert report.usb_step({"reason": "converted", "rekordbox": entries}) == report.USB_STEP
    assert report.usb_step({"reason": "repointed", "rekordbox": entries}) == report.USB_STEP
    assert report.usb_step({"reason": "renamed", "rekordbox": entries}) is None
    assert report.usb_step({"reason": "converted", "rekordbox": None}) is None
    assert report.usb_step({"reason": "swapped"}) is None and report.usb_step(None) is None
