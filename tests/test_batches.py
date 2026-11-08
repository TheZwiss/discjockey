"""AIFF batches (discjockey/batches.py; plan stage B §1.10, §5.2 B5): one session and one backup for N tracks, a skip
or a failure that goes on, Stop, Resume, rekordbox opening mid-batch, batch undo, "checked", and a crash. Every library
and rekordbox library is built in tmp_path."""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import EXACT, FIXTURES, NOW, never, song
from discjockey import batches, convert, db, library, quality, upgrades
from discjockey.align import Alignment
from discjockey.audio import write_tags
from discjockey.events import BatchProgress, CancelToken
from discjockey.library import Paths, load_state
from discjockey.rekordbox import backup as rbbackup
from discjockey.rekordbox import master
from discjockey.rekordbox import session as rbsession
from discjockey.rekordbox.locate import Place
from rekordbox_helpers import (
    KEYS, _open, clicks, dump, make_anlz, make_master, ppth_tag, pqtz_tag, pwv3_from, pwv3_tag, save_library,
    write_wav,
)

pytestmark = needs_ffmpeg
D = 1105  # rekordbox's offset for clicks-lame.mp3, 44.1 kHz samples
DIFFERENT = Alignment("different", text="doesn't line up")


class PowerOff(BaseException):
    """The process dies here: nothing after it runs."""


@dataclass
class Lib:
    paths: Paths
    place: Place
    folder: Path
    tracks: list[str]     # song keys, in the order of `kinds`
    olds: list[str]       # their current files (music-folder relative)

    def entry(self, i: int) -> dict:
        return load_state(self.paths)["tracks"][self.tracks[i]]

    def row(self, i: int) -> dict:
        with master.open_read(self.place, False) as m:
            cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (str(i + 1),))
            return dict(zip([c[0] for c in cur.description], cur.fetchone()))

    def dump(self):
        return dump(self.place.db)

    def music(self) -> dict[str, bytes]:
        root = self.paths.root
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
                if p.is_file() and ".discjockey" not in p.relative_to(root).parts}

    def batch(self, batch_id: int):
        with db.connect(self.paths.db_file) as conn:
            return db.aiff_batch(conn, batch_id)


def make_lib(tmp_path: Path, monkeypatch, kinds: list[str]) -> Lib:
    """One song per kind, all parked with a lossless upgrade of the same edit (L = 0):
    `mp3` (rekordbox holds it, analysed), `mp3_plain` (rekordbox holds it, not analysed), `mp3_free` (rekordbox
    doesn't hold it), `aiff` (an AIFF rekordbox holds), `stale` (the stored alignment is a different edit)."""
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    folder = tmp_path / "rb"
    wav = write_wav(tmp_path / "clicks.wav", clicks(6, 44100), 44100)
    rows, library_, olds, analysed = [], {}, [], []
    for i, kind in enumerate(kinds):
        tid = f"t{i}aaaaaaa"
        if kind in ("mp3", "mp3_plain", "mp3_free", "stale"):
            old = f"Library/A/Old {i}.mp3"
            (paths.root / old).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURES / "clicks-lame.mp3", paths.root / old)
        else:
            old = f"Library/A/Artist - Song {i}.aiff"
            (paths.root / old).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "pcm_s16be", "-f",
                            "aiff", str(paths.root / old)], check=True)
            write_tags(paths.root / old, title=f"Song {i}", artists=("Artist",), album="", isrc=None, label=None,
                       cover=None, comment="")
        parked = f"Upgrades ready/A/Artist - Song {i}.aiff"
        (paths.root / parked).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(paths.root / old), "-ar", "44100", "-ac",
                        "2", "-c:a", "pcm_s16be", "-f", "aiff", str(paths.root / parked)], check=True)
        write_tags(paths.root / parked, title=f"Song {i}", artists=("Artist",), album="Album", isrc="ISRC00000001",
                   label="Label", cover=None, comment="Qobuz FLAC · verified lossless")
        alignment = DIFFERENT if kind == "stale" else EXACT
        library_[tid] = song(old, title=f"Song {i}",
                             upgrade={"file": parked, "source": "qobuz", "source_id": f"q{i}",
                                      "source_format": "flac", "found": "2026-10-10",
                                      "alignment": alignment.to_dict()})
        olds.append(old)
        if kind != "mp3_free":
            rows.append({"ID": str(i + 1), "path": os.path.abspath(paths.root / old), "cues": 2, "artist": "Artist",
                         "album": "", "Title": f"Song {i}" if kind == "aiff" else ""})
            if kind in ("mp3", "mp3_plain", "stale"):
                analysed.append((i, kind))
    make_master(folder, rows, anlz=True)
    for i, kind in analysed:
        name = os.path.basename(paths.root / olds[i])
        dat = folder / f"share/PIONEER/USBANLZ/{rows.index(next(r for r in rows if r['ID'] == str(i + 1))):03x}" \
                       f"/{i + 1}/ANLZ0000.DAT"
        make_anlz(dat, [ppth_tag("?/" + name), pqtz_tag(40)])
        if kind == "mp3_plain":
            dat.with_suffix(".EXT").unlink()
        else:
            audio, rate = quality.decode_mono(paths.root / olds[i])
            make_anlz(dat.with_suffix(".EXT"), [ppth_tag("?/" + name), pwv3_tag(pwv3_from(audio, rate, D / 44100))])
    save_library(paths, library_)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    return Lib(paths, Place(folder / "master.db", folder / "share", "override", None), folder, list(library_), olds)


def start(lib: Lib, indexes=None, started_by="user") -> int:
    return batches.start(lib.paths, [(lib.tracks[i], "same_track") for i in (indexes or range(len(lib.tracks)))],
                         started_by=started_by, now=lambda: NOW)


def go(lib: Lib, batch_id: int, *, resume=False, running=never, events=None, compare=lambda a, b: EXACT, token=None):
    fn = batches.resume if resume else batches.run
    return fn(lib.paths, batch_id, emit=(events.append if events is not None else (lambda e: None)), token=token,
              compare=compare, now=lambda: NOW, running=running, place=lib.place)


def states(lib: Lib, batch_id: int) -> list[str]:
    return [i.state for i in lib.batch(batch_id).items]


def backups_of(lib: Lib):
    return rbbackup.backups(lib.paths)


# --- a whole batch ---

def test_a_mixed_batch_uses_one_session_and_one_backup(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    opened = []
    real = rbsession.Session.open.__func__
    monkeypatch.setattr(rbsession.Session, "open", classmethod(
        lambda cls, *a, **k: (opened.append(1), real(cls, *a, **k))[1]))
    events = []
    batch_id = start(lib)
    result = go(lib, batch_id, events=events)
    assert len(opened) == 1                                     # one session: one rekordbox.lock, one read open
    assert (result.state, result.stop_reason, result.total, result.done, result.skipped, result.failed) == \
        ("done", None, 3, 3, 0, 0)
    assert [(i.track, i.state) for i in result.results] == [(t, "done") for t in lib.tracks]
    [only] = backups_of(lib)                                    # one backup for all three, named by the batch
    assert result.backup == only.id == lib.batch(batch_id).backup and batch_id in only.batches
    assert lib.batch(batch_id).ended == NOW.isoformat(timespec="seconds")
    # the two MP3s became AIFFs that rekordbox's tracks play; the AIFF kept its file and got rekordbox's text
    for i in (0, 2):
        new = f"Library/A/Artist - Song {i}.aiff"
        assert lib.entry(i)["path"] == new and lib.row(i)["FolderPath"] == str(lib.paths.root / new)
        assert result.results[i].path == new and result.results[i].rekordbox == {"entries": [str(i + 1)], "kept": []}
        assert (lib.paths.root / "Superseded" / f"A/Old {i}.mp3").is_file()
    assert lib.entry(1)["path"] == lib.olds[1] and lib.row(1)["FileSize"] == (lib.paths.root / lib.olds[1]).stat().st_size
    assert result.results[1].rekordbox == {"entries": ["2"], "kept": []}
    assert lib.entry(1)["rekordbox_check"]["reload_tag"] is False
    assert [(e.done, e.total, e.track_id) for e in events] == [
        (0, 3, lib.tracks[0]), (1, 3, lib.tracks[1]), (2, 3, lib.tracks[2]), (3, 3, None)]
    assert all(isinstance(e, BatchProgress) and e.batch_id == batch_id for e in events)
    assert events[0].name == "Artist - Song 0" and events[-1].name is None
    log = lib.paths.operations_log.read_text()
    assert log.count('"operation": "upgrade_same_track"') == 3 and log.count('"result": "done"') == 3
    assert lib.paths.not_lossless_md.exists()


def test_a_batch_of_one(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    result = go(lib, start(lib))
    assert (result.state, result.total, result.done) == ("done", 1, 1)
    assert lib.entry(0)["rekordbox_check"]["reason"] == "repointed"


def test_a_skipped_item_goes_on_and_a_stale_alignment_is_asked_again(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain", "mp3", "stale"])
    before = lib.music()
    rows_before = lib.row(0)
    batch_id = start(lib)
    result = go(lib, batch_id)
    assert (result.state, result.done, result.skipped, result.failed) == ("done", 1, 2, 0)
    assert [(i.state, i.reason) for i in result.results] == [("skipped", "not_analysed"), ("done", None),
                                                             ("skipped", "needs_choice")]
    assert "analysed" in result.results[0].message and result.results[0].path is None
    # the skipped ones were not touched: files, records and rekordbox's rows as they were
    assert lib.row(0) == rows_before and (lib.paths.root / lib.olds[0]).read_bytes() == before[lib.olds[0]]
    assert lib.entry(0)["upgrade"] and lib.entry(2)["upgrade"] and not lib.entry(1)["upgrade"]
    assert [i.reason for i in lib.batch(batch_id).items] == ["not_analysed", None, "needs_choice"]


def test_a_refusal_with_detail_is_stored(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    monkeypatch.setattr(convert, "free_space", lambda path: 10)
    with pytest.raises(batches.Refused) as err:
        go(lib, start(lib))
    [item] = err.value.result.results
    assert (item.state, item.reason) == ("skipped", "space") and "needed" in item.message
    with db.connect(lib.paths.db_file) as conn:
        [stored] = db.aiff_batch(conn, err.value.result.batch).items
    assert stored.result["detail"]["free"] and lib.entry(0)["upgrade"]


def test_nothing_eligible_is_refused(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["stale"])
    with pytest.raises(batches.Refused) as one:
        go(lib, start(lib))
    assert "Not swapped" not in str(one.value) and "different edit" in str(one.value)  # the one item's own words
    assert (one.value.result.state, one.value.result.skipped) == ("done", 1)
    (tmp_path / "two").mkdir()
    lib = make_lib(tmp_path / "two", monkeypatch, ["stale", "stale"])
    with pytest.raises(batches.Refused) as two:
        go(lib, start(lib))
    assert str(two.value) == batches.NOTHING_ELIGIBLE and [i.reason for i in two.value.result.results] == \
        ["needs_choice", "needs_choice"]


def test_a_failure_goes_on_with_its_plain_words(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    real = convert.build_staged
    calls = []

    def flaky(parked, staged, n):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("Input/output error")
        return real(parked, staged, n)

    monkeypatch.setattr(convert, "build_staged", flaky)
    batch_id = start(lib)
    result = go(lib, batch_id)
    assert (result.state, result.done, result.failed) == ("done", 1, 1)
    first = result.results[0]
    assert first.state == "failed" and first.reason is None and "Input/output error" in first.message
    assert lib.entry(0)["upgrade"] and not (lib.paths.tmp / lib.tracks[0]).exists()
    assert lib.batch(batch_id).items[0].reason == first.message       # the failure's words are the stored reason
    assert lib.paths.operations_log.read_text().count('"result": "failed"') == 1


def test_a_swap_that_does_not_line_up_when_measured_again_is_skipped(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3"])
    batch_id = start(lib)
    calls = iter([DIFFERENT])
    result = go(lib, batch_id, compare=lambda a, b: next(calls, EXACT))
    assert [(i.state, i.reason) for i in result.results] == [("skipped", "needs_choice"), ("done", None)]
    assert "Not swapped" in result.results[0].message


# --- Stop, Resume, rekordbox opening ---

def test_stop_between_items_then_resume(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    token = CancelToken()
    batch_id = start(lib)
    seen = []

    def emit(event):
        seen.append(event)
        if event.track_id == lib.tracks[0]:
            token.cancel()                      # Stop while the first item is in work: it finishes, the next doesn't

    with pytest.raises(batches.Stopped) as stopped:
        batches.run(lib.paths, batch_id, emit=emit, token=token, compare=lambda a, b: EXACT, now=lambda: NOW,
                    running=never, place=lib.place)
    result = stopped.value.result
    assert (result.state, result.stop_reason, result.done) == ("stopped", "stop", 1)
    assert states(lib, batch_id) == ["done", "planned", "planned"]
    assert lib.entry(1)["upgrade"] and lib.entry(2)["upgrade"] and lib.entry(0)["path"].endswith("Song 0.aiff")
    first_entry = lib.entry(0)
    seen.clear()
    done = go(lib, batch_id, resume=True, events=seen)
    assert (done.state, done.stop_reason, done.done) == ("done", None, 3)
    assert lib.entry(0) == first_entry          # Resume runs only the planned ones
    assert [(e.done, e.total, e.track_id) for e in seen] == [(1, 3, lib.tracks[1]), (2, 3, lib.tracks[2]),
                                                             (3, 3, None)]
    with pytest.raises(ValueError):             # a finished batch is not resumed
        go(lib, batch_id, resume=True)


def test_resume_asks_eligibility_again(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    token = CancelToken()
    token.cancel()                               # Stop pressed before the first item
    batch_id = start(lib)
    with pytest.raises(batches.Stopped):
        go(lib, batch_id, token=token)
    assert states(lib, batch_id) == ["planned", "planned"]
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[1]] = {**state["tracks"][lib.tracks[1]], "upgrade": None}   # discarded meanwhile
    library.save_state(lib.paths, state)
    result = go(lib, batch_id, resume=True)
    assert [(i.state, i.reason) for i in result.results] == [("done", None), ("skipped", "no_upgrade")]


def test_rekordbox_opening_while_an_item_is_in_work_rolls_it_back(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    on = {"v": False}
    calls = []

    def compare(a, b):
        calls.append(1)
        if len(calls) == 2:
            on["v"] = True                       # rekordbox starts while the second track is being measured
        return EXACT

    batch_id = start(lib)
    row_before = lib.row(1)
    music_before = {k: v for k, v in lib.music().items() if k.startswith(("Library/A/Old 1", "Upgrades ready/A/Artist - Song 1"))}
    with pytest.raises(batches.RekordboxOpen) as opened:
        go(lib, batch_id, running=lambda: on["v"], compare=compare)
    result = opened.value.result
    assert (result.state, result.stop_reason, result.done) == ("stopped", "rekordbox_open", 1)
    assert "stopped after 1 of 3" in str(opened.value) and "Resume" in str(opened.value)
    assert states(lib, batch_id) == ["done", "planned", "planned"]
    assert lib.row(1) == row_before and lib.entry(1)["upgrade"]
    assert {k: v for k, v in lib.music().items() if k in music_before} == music_before
    assert load_state(lib.paths)["pending"] == []
    on["v"] = False                              # rekordbox quit: Resume does the rest
    done = go(lib, batch_id, resume=True, running=lambda: on["v"])
    assert (done.state, done.done) == ("done", 3)
    assert lib.batch(batch_id).backup == done.backup


def test_rekordbox_opening_between_items_stops_before_the_next_even_an_aiff_swap(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "aiff"])
    on = {"v": False}

    def compare(a, b):
        on["v"] = True                           # during the first swap
        return EXACT

    batch_id = start(lib)
    with pytest.raises(batches.RekordboxOpen) as opened:
        go(lib, batch_id, running=lambda: on["v"], compare=compare)
    assert states(lib, batch_id) == ["done", "planned"] and opened.value.result.stop_reason == "rekordbox_open"
    check = lib.entry(0)["rekordbox_check"]
    assert check["reload_tag"] is True and check.get("rekordbox") is None    # opened: no rekordbox write, Reload Tag
    assert lib.entry(1)["upgrade"] and lib.entry(1)["path"] == lib.olds[1]   # the second swap did not start


def test_rekordbox_open_at_the_start_changes_nothing(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3"])
    batch_id = start(lib)
    db_before, music_before = lib.dump(), lib.music()
    with pytest.raises(batches.RekordboxOpen) as opened:
        go(lib, batch_id, running=lambda: True)
    assert str(opened.value) == convert.REKORDBOX_OPEN
    assert (opened.value.result.state, opened.value.result.stop_reason) == ("stopped", "rekordbox_open")
    assert states(lib, batch_id) == ["planned", "planned"]
    assert lib.dump() == db_before and lib.music() == music_before and backups_of(lib) == []


def test_a_batch_that_needs_no_rekordbox_write_goes_ahead_while_rekordbox_runs(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3_free"])
    db_before = lib.dump()
    result = go(lib, start(lib), running=lambda: True)
    assert (result.state, result.done) == ("done", 2)
    assert lib.dump() == db_before and backups_of(lib) == []           # rekordbox untouched, no backup needed
    assert lib.entry(0)["rekordbox_check"]["reload_tag"] is True       # the swap keeps its Reload Tag step
    assert "isn't in your rekordbox collection" in result.results[1].message and result.results[1].rekordbox is None


def test_another_window_holding_the_lock_is_busy(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    batch_id = start(lib)
    lib.paths.support.mkdir(parents=True, exist_ok=True)
    fd = os.open(lib.paths.support / "rekordbox.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(batches.Busy) as busy:
            go(lib, batch_id)
    finally:
        os.close(fd)
    assert str(busy.value) == batches.BUSY
    assert states(lib, batch_id) == ["planned"] and lib.batch(batch_id).state == "stopped"
    assert go(lib, batch_id, resume=True).done == 1


# --- crash ---

def test_a_crash_leaves_the_batch_running_and_the_next_start_stops_it(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    batch_id = start(lib)
    real = convert.same_track
    calls = []

    def dies(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise PowerOff()
        return real(*a, **k)

    monkeypatch.setattr(convert, "same_track", dies)
    with pytest.raises(PowerOff):
        go(lib, batch_id)
    assert lib.batch(batch_id).state == "running" and states(lib, batch_id) == ["done", "planned"]
    monkeypatch.setattr(convert, "same_track", real)
    state = load_state(lib.paths)
    library.recover_pending(lib.paths, state)                           # the next start
    row = lib.batch(batch_id)
    assert (row.state, row.stop_reason) == ("stopped", "crash") and row.backup
    done = go(lib, batch_id, resume=True)
    assert (done.state, done.done) == ("done", 2)


def test_a_swap_a_crash_cut_off_is_finished_with_its_item(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3"])
    batch_id = start(lib)

    def die(*a, **k):
        raise PowerOff

    monkeypatch.setattr(upgrades, "_write_text", die)                   # after the file write, before the step ends
    with pytest.raises(PowerOff):
        go(lib, batch_id)
    monkeypatch.undo()
    assert states(lib, batch_id) == ["planned", "planned"]
    messages = library.recover_pending(lib.paths, load_state(lib.paths))
    assert messages == [("Finished an interrupted swap for Artist - Song 0", True)]
    row = lib.batch(batch_id)
    assert [i.state for i in row.items] == ["done", "planned"] and (row.state, row.stop_reason) == ("stopped", "crash")
    assert row.items[0].result["path"] == lib.olds[0] and lib.entry(0)["rekordbox_check"]["reload_tag"] is True
    assert go(lib, batch_id, resume=True).done == 2


def test_recover_closes_what_has_nothing_left(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    batch_id = start(lib)
    go(lib, batch_id)
    with db.connect(lib.paths.db_file) as conn:
        db.set_aiff_batch(conn, batch_id, state="running")              # a crash right after the last item
    assert batches.recover(lib.paths, now=lambda: NOW) == []
    assert lib.batch(batch_id).state == "done"
    other = start(lib)                                                   # a running batch with a planned item
    assert batches.recover(lib.paths, now=lambda: NOW) == [other]
    assert (lib.batch(other).state, lib.batch(other).stop_reason) == ("stopped", "crash")


# --- undo and "checked" ---

def test_batch_undo_goes_newest_first_and_lists_what_was_refused(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    batch_id = start(lib)
    go(lib, batch_id)
    con = _open(lib.place.db, KEYS[0])                                   # the user relocates the first track
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    events = []
    result = batches.undo(lib.paths, batch_id, emit=events.append, running=never, place=lib.place,
                          now=lambda: NOW)
    assert [(r.track, r.state) for r in result.results] == [
        (lib.tracks[2], "undone"), (lib.tracks[1], "undone"), (lib.tracks[0], "refused")]
    assert (result.batch, result.total, result.undone, result.refused, result.failed) == (batch_id, 3, 2, 1, 0)
    assert result.results[2].reason == "relocated" and "relocated" in result.results[2].message
    assert states(lib, batch_id) == ["done", "undone", "undone"]
    assert lib.entry(2)["path"] == lib.olds[2] and lib.entry(2)["upgrade"] and lib.entry(0)["path"].endswith("Song 0.aiff")
    assert lib.row(2)["FolderPath"] == str(lib.paths.root / lib.olds[2])
    assert [(e.done, e.total) for e in events] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert lib.paths.operations_log.read_text().count('"operation": "undo_upgrade"') == 2


def test_undo_while_rekordbox_runs_is_refused_per_track(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    batch_id = start(lib)
    go(lib, batch_id)
    result = batches.undo(lib.paths, batch_id, running=lambda: True, place=lib.place)
    assert [(r.state, r.reason) for r in result.results] == [("refused", "rekordbox_open")] * 2
    assert "Quit rekordbox" in result.results[0].message and states(lib, batch_id) == ["done", "done"]
    assert lib.entry(0)["path"].endswith("Song 0.aiff")


def test_undo_of_some_tracks_marks_their_items(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    batch_id = start(lib)
    go(lib, batch_id)
    result = batches.undo(lib.paths, [lib.tracks[0], lib.tracks[1], "nope"], running=never, place=lib.place)
    assert [r.track for r in result.results] == [lib.tracks[1], lib.tracks[0], "nope"]    # newest first
    assert [r.state for r in result.results] == ["undone", "undone", "refused"] and result.batch is None
    assert result.results[2].reason is None
    assert states(lib, batch_id) == ["undone", "undone"]
    again = batches.undo(lib.paths, [lib.tracks[0]], running=never, place=lib.place)
    assert again.results[0].state == "refused" and "no upgrade to undo" in again.results[0].message


def test_checked_ends_the_undo_and_frees_the_backup(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    batch_id = start(lib)
    result = go(lib, batch_id)
    held = [lib.entry(i)["rekordbox_check"]["undo"]["held"] for i in (0, 1)]
    assert all((lib.paths.root / h).is_file() for h in held)
    with db.connect(lib.paths.db_file) as conn:
        db.set_aiff_batch(conn, batch_id, state="stopped", stop_reason="stop")   # as if it had been stopped
        assert db.aiff_backups_in_use(conn) == {result.backup}
    done = batches.checked(lib.paths, [lib.tracks[0], lib.tracks[1], "nope"], now=lambda: NOW)
    assert [r.track_id for r in done] == lib.tracks and all(r.section == "rekordbox_checked" for r in done)
    assert all(lib.entry(i)["rekordbox_check"] is None for i in (0, 1))
    assert not any((lib.paths.root / h).exists() for h in held)
    assert batches.tracks_of(lib.paths, batch_id) == lib.tracks
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_backups_in_use(conn) == set()                    # nothing left to resume: the batch ended
    assert lib.batch(batch_id).state == "done"
    again = batches.undo(lib.paths, [lib.tracks[0]], running=never, place=lib.place)
    assert again.results[0].state == "refused"                          # "checked" ended the undo
    assert batches.checked(lib.paths, lib.tracks) == []                 # nothing left to check


# --- records ---

def test_start_checks_its_items(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    with pytest.raises(ValueError):
        batches.start(lib.paths, [], now=lambda: NOW)
    with pytest.raises(ValueError):
        batches.start(lib.paths, [(lib.tracks[0], "convert")], now=lambda: NOW)
    batch_id = start(lib, started_by="upgrade_all")
    row = lib.batch(batch_id)
    assert (row.kind, row.started_by, row.state) == ("upgrade", "upgrade_all", "running")
    shown = batches.result_of(lib.paths, batch_id)
    assert (shown.state, shown.total, shown.done) == ("running", 1, 0) and shown.results[0].state == "planned"
    with pytest.raises(ValueError):
        batches.result_of(lib.paths, 99)
    with pytest.raises(ValueError):
        go(lib, batch_id, resume=True)                                   # running, not stopped
