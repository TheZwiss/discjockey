"""The AIFF in-place swap in a batch's rekordbox session (upgrades.swap(session=…); plan stage B §0.6, §0.7, §5.2 B4):
with rekordbox closed and the file in its library, rekordbox's text columns and `FileSize` are written (the user's
own edits kept) and undone per field; while rekordbox runs (or ran when the batch began) the swap is today's with
`reload_tag: true`; a crash after the file write and before the rekordbox write is finished without writing
rekordbox. Libraries in tmp_path only."""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager

import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg
from convert_helpers import EXACT, NOW, never
from discjockey import db, library, upgrades
from discjockey.audio import write_tags
from discjockey.library import Paths, load_state
from discjockey.planner import ENTRY_KEYS
from discjockey.rekordbox import master
from discjockey.rekordbox.locate import Place
from discjockey.rekordbox.session import Session
from discjockey.report import SWAPPED_CHECK, SWAPPED_WRITTEN_CHECK, check_text
from rekordbox_helpers import TABLES, clicks, diff, dump, make_master, save_library, write_wav, writer

pytestmark = needs_ffmpeg
TID = "t1aaaaaaa"
CURRENT = "Library/A/Artist - Song.aiff"
PARKED = "Upgrades ready/A/Artist - Song.aiff"
STAMPS = {"rb_local_usn", "updated_at"}


class PowerOff(BaseException):
    pass


def aiff(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_s16be", "-f", "aiff",
                    str(dst)], check=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    wav = write_wav(tmp_path / "clicks.wav", clicks(6, 44100), 44100)
    aiff(wav, paths.root / CURRENT)
    write_tags(paths.root / CURRENT, title="Song", artists=("Artist",), album="", isrc=None, label=None, cover=None,
               comment="")
    aiff(wav, paths.root / PARKED)
    write_tags(paths.root / PARKED, title="Song", artists=("Artist",), album="Album", isrc="ISRC00000001",
               label="Label", cover=None, comment="Qobuz FLAC · verified lossless")
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=6000, folder="A", path=CURRENT,
             status="fake_lossless", source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=16000,
             rejected_sources=[], in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-10",
             upgrade={"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                      "found": "2026-10-10", "alignment": EXACT.to_dict()})
    save_library(paths, {TID: e})
    folder = tmp_path / "rb"
    make_master(folder, [{"ID": "1", "path": os.path.abspath(paths.root / CURRENT), "artist": "Artist", "album": "",
                          "Title": "Song", "cues": 2}], anlz=True)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    place = Place(folder / "master.db", folder / "share", "override", None)
    return paths, place


@contextmanager
def batch(paths, place, running=never):
    with Session.open(paths, place=place, running=running, items_need_write=lambda view: False) as s:
        yield s


def swap(paths, s=None):
    state = load_state(paths)
    r = upgrades.swap(paths, state, TID, dict(state["tracks"][TID]["upgrade"]), lambda a, b: EXACT, session=s)
    return r, state


def row(place) -> dict:
    with master.open_read(place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = '1'")
        r = dict(zip([c[0] for c in cur.description], cur.fetchone()))
        for col, table in (("AlbumID", "djmdAlbum"), ("LabelID", "djmdLabel"), ("ArtistID", "djmdArtist")):
            found = m.con.execute(f"SELECT Name FROM {table} WHERE ID = ?", (r[col],)).fetchone()
            r[col[:-2]] = found[0] if found else None
        return r


def test_a_swap_in_a_batch_writes_rekordboxs_text_and_undo_puts_it_back(env):
    paths, place = env
    old_audio, before = (paths.root / CURRENT).read_bytes(), dump(place.db)
    with batch(paths, place) as s:
        _r, state = swap(paths, s)
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["reload_tag"] is False and check["rekordbox"] == {"entries": ["1"], "kept": []}
    assert check_text(check) == SWAPPED_WRITTEN_CHECK and check_text({**check, "reload_tag": True}) == SWAPPED_CHECK
    r = row(place)
    assert (r["Title"], r["Artist"], r["Album"], r["Label"]) == ("Song", "Artist", "Album", "Label")
    assert (r["ISRC"], r["Commnt"]) == ("ISRC00000001", "Qobuz FLAC · verified lossless")
    assert r["FileSize"] == (paths.root / CURRENT).stat().st_size and r["FolderPath"] == str(paths.root / CURRENT)
    changed = {(t, c) for t, _i, c, _a, _b in diff(before, dump(place.db))}
    assert changed <= {("djmdContent", c) for c in ("AlbumID", "LabelID", "ISRC", "Commnt", "FileSize", *STAMPS)} | {
        ("djmdAlbum", "<row>"), ("djmdLabel", "<row>"), ("agentRegistry", "int_1")}
    assert check["undo"]["repoint"]["rows"][0]["identity_before"] == check["undo"]["repoint"]["rows"][0][
        "identity_after"]  # a swap writes no path

    con = writer(place.db)  # the user edits the comment in rekordbox afterwards
    con.execute("UPDATE djmdContent SET Commnt = 'my notes' WHERE ID = '1'")
    con.commit()
    con.close()
    state = load_state(paths)
    upgrades.undo(paths, state, TID)
    assert (paths.root / CURRENT).read_bytes() == old_audio
    r = row(place)
    was = before_row(before)
    assert {k: r[k] for k in ("AlbumID", "LabelID", "ISRC", "FileSize")} == {
        k: was[k] for k in ("AlbumID", "LabelID", "ISRC", "FileSize")}  # back as they were
    assert r["Commnt"] == "my notes"  # the user's edit since stays


def before_row(before) -> dict:
    names = [n for n, _ in TABLES["djmdContent"]]
    return dict(zip(names, next(r for r in before["djmdContent"] if r[0] == "1")))


@pytest.mark.parametrize("how", ["running_at_start", "no_session"])
def test_without_a_closed_rekordbox_the_swap_is_todays(env, how):
    paths, place = env
    before = dump(place.db)
    if how == "no_session":
        _r, state = swap(paths)
        check = state["tracks"][TID]["rekordbox_check"]
        assert "reload_tag" not in check and "repoint" not in check["undo"]  # exactly as before stage B
    else:
        with batch(paths, place, running=lambda: True) as s:
            _r, state = swap(paths, s)
        check = state["tracks"][TID]["rekordbox_check"]
        assert check["reload_tag"] is True and check["rekordbox"] is None
    assert check_text(check) == SWAPPED_CHECK
    assert dump(place.db) == before
    upgrades.undo(paths, load_state(paths), TID)  # undone without rekordbox
    assert dump(place.db) == before


def test_rekordbox_opening_at_the_commit_leaves_reload_tag(env):
    paths, place = env
    before = dump(place.db)
    calls = {"n": 0}

    def running():  # closed at the start, the read and the write's checks; open at the commit check
        calls["n"] += 1
        return calls["n"] > 5

    with batch(paths, place, running=running) as s:
        _r, state = swap(paths, s)
    check = state["tracks"][TID]["rekordbox_check"]
    assert calls["n"] == 6  # the commit check was the one that saw it
    assert check["reload_tag"] is True and check["rekordbox"] is None and "repoint" not in check["undo"]
    assert dump(place.db) == before and state["tracks"][TID]["upgrade"] is None


def test_a_crash_between_the_file_write_and_rekordbox_finishes_the_swap_only(env, monkeypatch):
    paths, place = env
    before = dump(place.db)

    def die(*a, **k):
        raise PowerOff

    monkeypatch.setattr(upgrades, "_write_text", die)
    with batch(paths, place) as s, pytest.raises(PowerOff):
        swap(paths, s)
    monkeypatch.undo()
    state = load_state(paths)
    messages = library.recover_pending(paths, state)
    assert messages == [("Finished an interrupted swap for Artist - Song", True)]
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["reload_tag"] is True and check["rekordbox"] is None
    assert dump(place.db) == before


def test_a_swap_whose_track_left_rekordbox_since_is_still_undone(env):
    paths, place = env
    old_audio = (paths.root / CURRENT).read_bytes()
    with batch(paths, place) as s:
        swap(paths, s)
    con = writer(place.db)  # the user removed the track from rekordbox's collection
    con.execute("UPDATE djmdContent SET rb_local_deleted = 1 WHERE ID = '1'")
    con.commit()
    con.close()
    gone = dump(place.db)
    upgrades.undo(paths, load_state(paths), TID)
    assert (paths.root / CURRENT).read_bytes() == old_audio
    assert [c for t, _i, c, _a, _b in diff(gone, dump(place.db)) if t == "djmdContent"] == []  # nothing to put back


MIK = "1A - Energy 6"


def test_a_comment_of_the_users_own_survives_the_swap_in_the_file_and_in_rekordbox(env):
    paths, place = env
    write_tags(paths.root / CURRENT, title="Song", artists=("Artist",), album="", isrc=None, label=None, cover=None,
               comment=MIK)
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET Commnt = ? WHERE ID = '1'", (MIK,))
    con.commit()
    con.close()
    with batch(paths, place) as s:
        _r, state = swap(paths, s)
    assert file_comment(paths.root / CURRENT) == MIK                     # the download's quality line did not replace it
    assert row(place)["Commnt"] == MIK and row(place)["Label"] == "Label"  # the rest is written as before
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"] == {"entries": ["1"], "kept": []}


def test_a_quality_line_of_ours_in_the_old_file_is_replaced_by_the_downloads(env):
    paths, place = env
    write_tags(paths.root / CURRENT, title="Song", artists=("Artist",), album="", isrc=None, label=None, cover=None,
               comment="YouTube Music OPUS · cutoff 16.0 kHz")
    with batch(paths, place) as s:
        swap(paths, s)
    assert file_comment(paths.root / CURRENT) == "Qobuz FLAC · verified lossless"


def file_comment(path) -> str:
    return str(AIFF(str(path)).tags.getall("COMM")[0].text[0])


def test_a_batch_swaps_check_names_its_batch(env):
    paths, place = env
    with batch(paths, place) as s:
        state = load_state(paths)
        with db.connect(paths.db_file) as conn:
            batch_id = db.start_aiff_batch(conn, "upgrade", "user", None, [(TID, "same_track")], NOW)
        upgrades.swap(paths, state, TID, dict(state["tracks"][TID]["upgrade"]), lambda a, b: EXACT, session=s,
                      batch=(batch_id, 0))
    assert state["tracks"][TID]["rekordbox_check"]["batch"] == batch_id


def test_a_crash_right_after_the_text_commit_finishes_without_reload_tag(env, monkeypatch):
    paths, place = env
    real = upgrades.mark_op

    def die_after_commit(p, state, op):
        if (op.get("check") or {}).get("reload_tag") is False:  # the mark that follows the commit
            raise PowerOff
        return real(p, state, op)

    monkeypatch.setattr(upgrades, "mark_op", die_after_commit)
    with batch(paths, place) as s, pytest.raises(PowerOff):
        swap(paths, s)
    monkeypatch.setattr(upgrades, "mark_op", real)
    state = load_state(paths)
    library.recover_pending(paths, state)
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["reload_tag"] is False and check["rekordbox"]["entries"] == ["1"]   # the text stands: no Reload Tag
    assert row(place)["Label"] == "Label"
    assert upgrades._text_stands(check["undo"]["repoint"])
    con = writer(place.db)  # a record whose values rekordbox doesn't hold (the commit never happened) says no
    con.execute("UPDATE djmdContent SET ISRC = 'OTHER' WHERE ID = '1'")
    con.commit()
    con.close()
    assert not upgrades._text_stands(check["undo"]["repoint"])


def test_the_swap_undo_keeps_rekordboxs_write_connection_closed_while_the_audio_moves(env, monkeypatch):
    from contextlib import contextmanager
    paths, place = env
    with batch(paths, place) as s:
        swap(paths, s)
    depth, seen = [0], []
    real_writer, real_audio = Session.writer, upgrades._undo_swap_audio

    @contextmanager
    def counting(self, *a, **k):
        with real_writer(self, *a, **k) as w:
            depth[0] += 1
            try:
                yield w
            finally:
                depth[0] -= 1

    def spy(*a, **k):
        seen.append(depth[0])
        return real_audio(*a, **k)

    monkeypatch.setattr(Session, "writer", counting)
    monkeypatch.setattr(upgrades, "_undo_swap_audio", spy)
    upgrades.undo(paths, load_state(paths), TID)
    assert seen == [0]
