"""Convert to AIFF for an own file (discjockey/convert.py `convert_file`; plan stage D §1.2, §5 D2; design
rekordbox-repoint §3.1, §3.5, §4, §5.5): the new AIFF on rekordbox's timeline, its tags, name and cover, the rekordbox
rows (every column of §5.5 and nothing else), the song's records, and every refusal with nothing written. Libraries
in tmp_path (tests/convert_helpers.py); crash recovery and undo are in test_convert_file_recovery.py."""
from __future__ import annotations

import subprocess

import numpy as np
import pytest
from mutagen.aiff import AIFF
from mutagen.id3 import APIC, COMM, ID3, TCON, TDRC, ID3NoHeaderError

from audio_helpers import TINY_JPEG, needs_ffmpeg, pcm, picture
from convert_helpers import NOW, TID, batch_row, file_facts_row, make_own, run_file, session, start_file_batch
from discjockey import audio, convert, library, report, upgrades
from discjockey.library import load_state
from discjockey.rekordbox import anlz, backup, eligible, master
from discjockey.rekordbox import write as rbwrite
from discjockey.rekordbox.session import Session
from discjockey.rekordbox.write import RekordboxOpened
from rekordbox_helpers import diff, dump, running_after

pytestmark = needs_ffmpeg
NEW = "Library/A/not_lossless/Artist - Song.aiff"  # a lossy song's AIFF stays in not_lossless/
CLEAN = {"entry": {"status": "lossless", "source_format": None}}  # an own lossless file: its AIFF is in Library/A/
CLEAN_NEW = "Library/A/Artist - Song.aiff"


def row_of(env, row_id="1") -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (row_id,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def mono(path) -> np.ndarray:
    """ffmpeg's decode of a file as 16-bit samples at 44.1 kHz, one channel (what rekordbox's timeline counts)."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "44100",
                        "-f", "s16le", "-acodec", "pcm_s16le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype="<i2")


def onsets(x: np.ndarray) -> np.ndarray:
    """The first sample of every click (a loud sample after more than 2000 quiet ones)."""
    loud = np.flatnonzero(np.abs(x) > 6500)
    return loud[np.r_[True, np.diff(loud) > 2000]]


def tags(path):
    return AIFF(str(path)).tags


# --- the audio: rekordbox's timeline, the library format ---

@pytest.mark.parametrize("kind", ["lame", "notag", "m4a", "wav48"])
def test_the_new_aiff_sits_on_rekordboxs_timeline(tmp_path, monkeypatch, kind):
    """A moment at t in ffmpeg's decode of the old file sits at t + d on rekordbox's timeline, so the AIFF holds the
    decode shifted by d (silence in front): the clicks land at rekordbox's positions to the sample."""
    env = make_own(tmp_path, monkeypatch, kind)
    root = env.paths.root
    r, state = run_file(env)
    old = mono(root / env.superseded)
    new = mono(root / r.path)
    d = env.d
    assert (kind, d > 0) in (("lame", True), ("notag", False), ("m4a", True), ("wav48", False))
    assert np.all(new[:d] == 0)
    n = min(len(new) - d, len(old))
    assert len(old) - n < 2
    if kind == "wav48":  # resampled by the library's filter, not ffmpeg's default: the same sound, not the same bits
        assert np.corrcoef(new[d:d + n], old[:n])[0, 1] > 0.99  # white-noise clicks: a filter's roll-off shows
        a, b = onsets(new), onsets(old) + d
        assert len(a) == len(b) > 20 and np.abs(a - b).max() <= 1
    else:  # 44.1 kHz: ffmpeg's decode to the bit, within the dither
        assert np.abs(new[d:d + n].astype(int) - old[:n].astype(int)).max() <= 3
        assert np.array_equal(onsets(new), onsets(old) + d)
    info = AIFF(str(root / r.path)).info
    assert (info.sample_rate, info.bits_per_sample) == (44100, 16)


def test_a_24_bit_96_khz_flac_becomes_16_bit_44_khz(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, "flac96", **CLEAN)
    r, state = run_file(env)
    info = AIFF(str(env.paths.root / r.path)).info
    assert (info.sample_rate, info.bits_per_sample) == (44100, 16)
    assert abs(info.length - 20) < 0.05 and r.path == CLEAN_NEW
    assert (env.paths.root / env.superseded).is_file() and env.superseded.endswith("/Old Name.flac")
    a, b = onsets(mono(env.paths.root / r.path)), onsets(mono(env.paths.root / env.superseded))
    assert len(a) == len(b) > 20 and np.abs(a - b).max() <= 2  # d = 0: the clicks stay where ffmpeg decodes them


def test_an_aiff_with_wrong_tags_is_copied_sample_for_sample_with_new_tags(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, "aiff", **CLEAN)
    old_samples = pcm(env.paths.root / env.old)
    r, state = run_file(env)
    assert np.array_equal(pcm(env.paths.root / r.path), old_samples)  # no resampling, no dither, no shift
    t = tags(env.paths.root / r.path)
    assert (str(t["TIT2"]), str(t["TPE1"]), str(t["TALB"])) == ("Song", "Artist", "Old Album")  # the record's names;
    assert "Wrong" not in str(t.pprint())                                                       # the album: the old file's
    assert tags(env.paths.root / env.superseded)["TIT2"].text == ["Wrong Title"]  # the old file is untouched
    assert eligible.is_clean_aiff(audio.file_facts(env.paths.root / r.path), state["tracks"][TID])
    assert isinstance(eligible.convert(state["tracks"][TID], audio.file_facts(env.paths.root / r.path),
                                       run_status(env), None), eligible.Skip)  # a second Convert has nothing to do


def run_status(env):
    with session(env) as s:
        return s.state


def test_the_old_file_holding_the_clean_name_makes_the_new_one_take_the_songs_id(tmp_path, monkeypatch):
    """Both files exist until rekordbox's commit, so the new AIFF can't take the old one's name (never overwrite)."""
    env = make_own(tmp_path, monkeypatch, "aiff", entry={"path": CLEAN_NEW, "status": "lossless"})
    old = (env.paths.root / CLEAN_NEW).read_bytes()
    r, state = run_file(env)
    assert r.path == "Library/A/Artist - Song [t1aaaa].aiff"
    assert (env.paths.root / env.superseded).read_bytes() == old and not (env.paths.root / CLEAN_NEW).exists()
    assert row_of(env)["FolderPath"] == str(env.paths.root / r.path)


# --- the step: files, rows, records ---

def test_convert_an_mp3_with_cues(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    old_bytes = (env.paths.root / env.old).read_bytes()
    before_entry = load_state(env.paths)["tracks"][TID]
    r, state = run_file(env)
    root = env.paths.root
    assert (r.section, r.path, r.status, r.source) == ("converted", NEW, "not_lossless", "manual")
    # files: the new AIFF with the clean name and tags, the old one mirrored into Superseded/ under its own name
    assert (root / env.superseded).read_bytes() == old_bytes and not (root / env.old).exists()
    assert env.superseded == "Superseded/A/Old Name.mp3"
    assert str(tags(root / NEW)["TIT2"]) == "Song" and str(tags(root / NEW)["TPE1"]) == "Artist"
    assert not (env.paths.tmp / TID).exists() and state["pending"] == []
    # the song: only its path changed; what it was made from stays (design §2.1); the check says "converted"
    e = state["tracks"][TID]
    for key in ("status", "source", "source_id", "source_format", "cutoff_hz", "source_kbps", "upgrade", "artist"):
        assert e[key] == before_entry[key], key
    assert e["path"] == NEW
    check = e["rekordbox_check"]
    assert {k: check[k] for k in ("reason", "since", "batch", "rekordbox")} == {
        "reason": "converted", "since": "2026-11-08", "batch": None, "rekordbox": {"entries": ["1"], "kept": []}}
    undo = check["undo"]
    assert (undo["kind"], undo["source"], undo["file"], undo["old"], undo["held"]) == ("convert", "file", NEW,
                                                                                         env.superseded, None)
    assert undo["before"]["path"] == env.old and undo["before"]["upgrade"] is None
    assert undo["file_key"] and undo["old_key"] and undo["repoint"]["dbid"] == "1234567890"
    assert load_state(env.paths)["tracks"][TID]["rekordbox_check"] == check
    assert not env.paths.undo.exists()          # nothing is kept for the undo: the old file is the audio
    assert report.check_text(check) == report.CONVERTED_CHECK and upgrades.can_undo(e)
    # rekordbox: the track plays the new file, its analysis files name it
    row = row_of(env)
    assert row["FolderPath"] == str(root / NEW) and row["FileNameL"] == "Artist - Song.aiff"
    assert (row["FileType"], row["BitDepth"], row["SampleRate"]) == (12, 16, 44100)
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"
    (b,) = backup.backups(env.paths)
    assert (b.batches, b.tracks) == ([], 1)
    assert "nothing to keep" not in r.note and "Kept" not in r.note


def test_the_file_row_keeps_what_it_was_made_from_and_gets_the_new_files_facts(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    assert file_facts_row(env) == (("A/Old Name.mp3", "import", "mp3", 44100, None, 64),)
    r, state = run_file(env)
    ((path, placed_by, codec, rate, bits, kbps),) = file_facts_row(env)
    assert (path, placed_by, codec, rate, bits) == ("A/not_lossless/Artist - Song.aiff", "app", "pcm_s16be", 44100, 16)
    assert kbps == audio.quality.probe(env.paths.root / NEW).kbps or kbps in (705, 706)
    # the snapshot shows them too, and a rescan reads nothing again (the content key is the file's)
    e = load_state(env.paths)["tracks"][TID]
    assert (e["file_codec"], e["file_rate"], e["file_bits"], e["status"], e["source_format"]) == (
        "pcm_s16be", 44100, 16, "not_lossless", "mp3")


def test_only_the_columns_of_design_5_5_change_in_rekordbox(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    before = dump(env.place.db)
    run_file(env)
    changed = diff(before, dump(env.place.db))
    cells = {(t, c) for t, _i, c, *_ in changed}
    assert cells == {
        ("djmdContent", c) for c in ("FolderPath", "FileNameL", "FileType", "FileSize", "BitDepth", "SampleRate",
                                     "BitRate", "Length", "Title", "Commnt", "rb_local_usn", "updated_at")
    } | {("contentFile", c) for c in ("Hash", "Size", "rb_local_usn", "updated_at")} | {("agentRegistry", "int_1")}
    untouched = [t for t in before if t not in ("djmdContent", "contentFile", "agentRegistry")]
    assert all(dump(env.place.db)[t] == before[t] for t in untouched)  # cues, playlists, history, tags, lookups ...
    assert {r[0] for r in dump(env.place.db)["djmdCue"]} == {r[0] for r in before["djmdCue"]}


def test_the_users_own_rekordbox_title_is_kept_and_said(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, row={"Title": "My Edit Name"})
    r, state = run_file(env)
    assert row_of(env)["Title"] == "My Edit Name"
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == ["title"]
    assert r.note.endswith("Kept your own title in rekordbox.")


# --- tags ---

def edit_old_tags(env, *frames):
    path = env.paths.root / env.old
    try:
        t = ID3(str(path))
    except ID3NoHeaderError:
        t = ID3()
    for frame in frames:
        t.setall(frame.FrameID, [frame])
    t.save(str(path))


def test_the_users_comment_genre_and_year_are_carried_over(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, row={"Commnt": "1A - Energy 6"})
    edit_old_tags(env, COMM(encoding=3, lang="eng", desc="", text="1A - Energy 6"), TCON(encoding=3, text="Deep House"),
                  TDRC(encoding=3, text="2019"))
    r, state = run_file(env)
    t = tags(env.paths.root / r.path)
    assert str(t.getall("COMM")[0].text[0]) == "1A - Energy 6"        # Mixed In Key's: key and energy, not a quality line
    assert (str(t["TCON"]), str(t.get("TYER") or t["TDRC"])) == ("Deep House", "2019")
    assert (row_of(env)["Commnt"], state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"]) == (
        "1A - Energy 6", [])
    assert audio.genre_year(env.paths.root / r.path) == ("Deep House", "2019")
    raw = (env.paths.root / r.path).read_bytes()
    assert b"TYER" in raw and b"TDRC" not in raw  # ID3v2.3 as every download writes it


def test_the_new_file_says_what_it_was_made_from(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    r, _state = run_file(env)
    assert str(tags(env.paths.root / r.path).getall("COMM")[0].text[0]) == "Your own file (MP3) · lossy"
    assert row_of(env)["Commnt"] == "Your own file (MP3) · lossy"


def test_the_records_album_isrc_and_the_old_files_label_are_written(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, entry={"album": "Record Album", "isrc": "ISRC00000007"})
    from mutagen.id3 import TPUB
    edit_old_tags(env, TPUB(encoding=3, text="Old Label"))
    r, _state = run_file(env)
    t = tags(env.paths.root / r.path)
    assert (str(t["TALB"]), str(t["TSRC"]), str(t["TPUB"])) == ("Record Album", "ISRC00000007", "Old Label")


def apic(path) -> bytes | None:
    frames = tags(path).getall("APIC")
    return bytes(frames[0].data) if frames else None


def test_the_cover_is_the_old_files_picture_made_cdj_safe(tmp_path, monkeypatch):
    big = picture(1200, 1200, "png")  # a 1200 px PNG: CDJs need a baseline JPEG up to 600 px
    env = make_own(tmp_path, monkeypatch)
    edit_old_tags(env, APIC(encoding=3, mime="image/png", type=3, desc="", data=big))
    r, _state = run_file(env)
    cover = apic(env.paths.root / r.path)
    assert cover is not None and cover != big and cover[:3] == b"\xff\xd8\xff" and len(cover) <= audio.COVER_MAX_BYTES
    assert max(audio._baseline_jpeg_size(cover)) <= audio.COVER_MAX_PX
    assert tags(env.paths.root / r.path).getall("APIC")[0].mime == "image/jpeg"


def test_the_cover_is_the_songs_image_when_it_has_one_and_falls_back_when_the_fetch_fails(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, entry={"image_url": "https://example.com/cover.jpg"})
    edit_old_tags(env, APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=picture(300, 300)))
    fetched = []
    monkeypatch.setattr(audio, "fetch_cover", lambda url: (fetched.append(url), TINY_JPEG)[1])
    r, _state = run_file(env)
    assert fetched == ["https://example.com/cover.jpg"] and apic(env.paths.root / r.path) == TINY_JPEG
    # a failing fetch (None, or raising) leaves the old file's picture
    for attempt, failing in enumerate((lambda url: None, lambda url: (_ for _ in ()).throw(OSError("offline")))):
        sub = tmp_path / f"again{attempt}"
        sub.mkdir()
        env = make_own(sub, monkeypatch, entry={"image_url": "https://example.com/cover.jpg"})
        mine = picture(300, 300)
        edit_old_tags(env, APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=mine))
        monkeypatch.setattr(audio, "fetch_cover", failing)
        r, _state = run_file(env)
        assert apic(env.paths.root / r.path) == mine  # 300 px baseline JPEG: byte for byte


# --- names and places ---

def test_a_taken_name_gets_the_songs_id_only_then(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, **CLEAN)
    (env.paths.root / CLEAN_NEW).write_bytes(b"someone else's file")
    r, state = run_file(env)
    assert r.path.startswith("Library/A/Artist - Song [") and r.path.endswith(".aiff")
    assert (env.paths.root / CLEAN_NEW).read_bytes() == b"someone else's file"
    assert row_of(env)["FolderPath"] == str(env.paths.root / r.path)


def test_a_lossless_songs_file_in_not_lossless_moves_up_and_a_lossy_one_stays(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, entry={"path": "Library/A/not_lossless/Old Name.mp3", "status": "lossless"})
    r, _state = run_file(env)
    assert r.path == CLEAN_NEW
    sub = tmp_path / "lossy"
    sub.mkdir()
    env = make_own(sub, monkeypatch, entry={"path": "Library/A/not_lossless/Old Name.mp3"})
    r, _state = run_file(env)
    old = _state["tracks"][TID]["rekordbox_check"]["undo"]["old"]
    assert r.path == NEW and old == "Superseded/A/Old Name.mp3" and (env.paths.root / old).is_file()


def test_the_dry_run_names_what_the_step_does(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    state = load_state(env.paths)
    music = env.music()
    new, superseded = convert.plan_file_names(env.paths, state, TID, state["tracks"][TID])
    assert (new, superseded) == (NEW, env.superseded)
    places = convert.space_needed(env.paths, env.paths.root / env.old, new)
    assert places and places[0][0] == env.paths.tmp and all(need > 0 for _p, need in places)
    assert env.music() == music and load_state(env.paths)["pending"] == []
    r, _state = run_file(env)
    assert (r.path, env.superseded) == (new, superseded)


# --- no rekordbox track ---

@pytest.mark.parametrize("rekordbox, holds_file", [(False, False), (True, False)])
def test_without_a_rekordbox_track_it_is_a_plain_conversion_and_the_check_says_so(tmp_path, monkeypatch, rekordbox,
                                                                                  holds_file):
    env = make_own(tmp_path, monkeypatch, rekordbox=rekordbox, holds_file=holds_file)
    before = dump(env.place.db) if rekordbox else None
    analysis = env.anlz_files()
    r, state = run_file(env)
    assert r.path == NEW and (env.paths.root / env.superseded).is_file() and r.note.endswith(convert.NO_TRACK_NOTE)
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["rekordbox"] is None and check["undo"]["repoint"] is None
    assert report.check_text(check) == report.CONVERTED_NO_TRACK_CHECK
    assert env.anlz_files() == analysis and backup.backups(env.paths) == []
    if rekordbox:
        assert dump(env.place.db) == before
    old = mono(env.paths.root / env.superseded)  # d = 0 without a track: the decode as it is
    assert np.abs(mono(env.paths.root / NEW)[:len(old)].astype(int) - old.astype(int)).max() <= 3
    assert file_facts_row(env)[0][1:5] == ("app", "pcm_s16be", 44100, 16)


def test_a_flac_without_a_waveform_needs_none_but_an_mp3_with_cues_does(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, "flac96", analysed=False, **CLEAN)
    r, _state = run_file(env)  # a FLAC can only sit at 0
    assert r.path == CLEAN_NEW and row_of(env)["FolderPath"] == str(env.paths.root / CLEAN_NEW)
    sub = tmp_path / "mp3"
    sub.mkdir()
    env = make_own(sub, monkeypatch, "lame", analysed=False)
    with pytest.raises(convert.Skipped) as err:
        run_file(env)
    assert err.value.reason == "not_analysed"


# --- the batch ---

def test_the_batch_item_is_done_with_the_step(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    batch = start_file_batch(env)
    r, state = run_file(env, batch=(batch, 0))
    (item,) = batch_row(env, batch).items
    assert (item.state, item.result["path"], item.result["rekordbox"]) == ("done", NEW, {"entries": ["1"], "kept": []})
    assert state["tracks"][TID]["rekordbox_check"]["batch"] == batch


# --- refusals: nothing written ---

def assert_nothing_changed(env, music, master_rows, analysis, entry):
    assert env.music() == music
    assert env.place is None or dump(env.place.db) == master_rows
    assert env.anlz_files() == analysis
    state = load_state(env.paths)
    assert state["pending"] == [] and state["tracks"][TID] == entry
    assert not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()
    assert file_facts_row(env)[0][1] == "import"


@pytest.mark.parametrize("case, reason", [
    ("not_analysed", "not_analysed"), ("timing", "timing"), ("cloud", "cloud"), ("space", "space"),
    ("unclean", "unclean"), ("unreadable", "rekordbox_unreadable"), ("downloaded", "downloaded"),
    ("no_name", "no_name"), ("upgrade_waits", "upgrade_waits"), ("clean_aiff", "clean_aiff")])
def test_refusals_change_nothing(tmp_path, monkeypatch, case, reason):
    kw = {"not_analysed": {"analysed": False}, "timing": {"extra_s": 0.03}, "cloud": {"row": {"usn": 5}},
          "downloaded": {"entry": {"source": "qobuz", "status": "lossless"}},
          "no_name": {"entry": {"artist": " "}},
          "upgrade_waits": {"entry": {"upgrade": {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz"}}}}
    kind = "aiff" if case == "clean_aiff" else "lame"
    env = make_own(tmp_path, monkeypatch, kind, **kw.get(case, {}))
    if case == "clean_aiff":  # tags that say what the record says: nothing to convert
        audio.write_tags(env.paths.root / env.old, title="Song", artists=("Artist",), album="", isrc=None, label=None,
                         cover=None, comment="")
    if case == "space":
        monkeypatch.setattr(convert, "free_space", lambda path: 1_000_000)
    if case == "unclean":
        env.place.db.with_name("master.db-wal").write_bytes(b"")
    if case == "unreadable":
        monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    with pytest.raises(convert.Skipped) as err:
        run_file(env)
    assert err.value.reason == reason
    if case == "space":
        assert err.value.detail["free"] == 1_000_000 and "needed, 1 MB free" in str(err.value)
    else:
        assert str(err.value) == (convert.REFUSED.get(reason) or convert.CONVERT_REFUSED[reason])
    if case == "unclean":
        env.place.db.with_name("master.db-wal").unlink()
    assert_nothing_changed(env, music, master_rows, analysis, entry)


@pytest.mark.parametrize("case", ["missing", "away"])
def test_a_file_that_is_gone_or_on_a_drive_that_is_away_is_refused(tmp_path, monkeypatch, case):
    env = make_own(tmp_path, monkeypatch)
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    if case == "missing":
        (env.paths.root / env.old).rename(env.paths.root / "A.bak")
        music = env.music()
    else:
        monkeypatch.setattr(library, "online", lambda path, roots: False)
        (env.paths.root / env.old).rename(env.paths.root / "A.bak")
        music = env.music()
    with pytest.raises(convert.Skipped) as err:
        run_file(env)
    assert err.value.reason == ("file_missing" if case == "missing" else "away")
    assert env.music() == music and dump(env.place.db) == master_rows and env.anlz_files() == analysis
    assert load_state(env.paths)["tracks"][TID] == entry


def test_rekordbox_running_while_its_library_cant_be_read_stops_the_batch_not_a_refusal(tmp_path, monkeypatch):
    """The batch's session normally refuses first (RekordboxOpen); a session that let it through (no item needs a
    write) still gets `RekordboxOpened` from the step, never a "can't read the library" refusal."""
    env = make_own(tmp_path, monkeypatch)
    monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music = env.music()
    state = load_state(env.paths)
    with Session.open(env.paths, place=env.place, running=lambda: True, items_need_write=lambda view: False) as s:
        with pytest.raises(RekordboxOpened):
            convert.convert_file(env.paths, state, TID, session=s, now=lambda: NOW)
    assert env.music() == music


def test_rekordbox_open_since_the_batch_began_stops_before_anything(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    with pytest.raises(RekordboxOpened):
        run_file(env, running=running_after(2))  # closed at the session's start, open from then on
    assert_nothing_changed(env, music, master_rows, analysis, entry)


def test_rekordbox_opening_at_the_commit_rolls_the_step_back(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    real = rbwrite.Writer.repoint
    monkeypatch.setattr(rbwrite.Writer, "repoint",
                        lambda self, c, a, **kw: real(self, c, a, **{**kw, "running": lambda: True}))
    with pytest.raises(RekordboxOpened):
        run_file(env)
    assert_nothing_changed(env, music, master_rows, analysis, entry)


def test_a_track_changed_meanwhile_is_refused_and_rolled_back(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    music, analysis = env.music(), env.anlz_files()
    real = rbwrite.Writer.repoint

    def moved_meanwhile(self, changes, splices, **kw):
        self.con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.mp3' WHERE ID = '1'")
        return real(self, changes, splices, **kw)
    monkeypatch.setattr(rbwrite.Writer, "repoint", moved_meanwhile)
    with pytest.raises(convert.Skipped) as err:
        run_file(env)
    assert err.value.reason == "changed" and str(err.value) == convert.REFUSED["changed"]
    assert env.music() == music and env.anlz_files() == analysis


def test_a_file_ffprobe_cant_read_is_a_failure_with_nothing_changed(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    (env.paths.root / env.old).write_bytes(b"not audio at all")
    music = env.music()
    with pytest.raises(convert.UpgradeProblem, match="couldn't read Old Name.mp3"):
        run_file(env)
    assert env.music() == music and load_state(env.paths)["pending"] == []


# --- nothing outside move_path ---

def test_every_file_move_goes_through_move_path(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    moves = []
    real = convert.move_path
    monkeypatch.setattr(convert, "move_path", lambda root, src, dst, staged, roots=None:
                        (moves.append((src, dst)), real(root, src, dst, staged, roots))[1])
    renames = []
    real_rename = library.os.rename
    monkeypatch.setattr(library.os, "rename", lambda s, d: (renames.append((str(s), str(d))), real_rename(s, d))[1])
    run_file(env)
    assert moves == [(f".discjockey/.tmp/{TID}/convert.aiff", NEW), (env.old, env.superseded)]
    assert len([1 for s, d in renames if "/Library/" in s or "/Library/" in d]) == 2  # nothing else in Library/


def test_the_staged_aiff_reaches_an_import_folder_on_another_drive(tmp_path, tmp_path_factory, monkeypatch):
    music = tmp_path_factory.mktemp("drive") / "Music"
    env = make_own(tmp_path, monkeypatch, rekordbox=False, entry={"path": str(music / "Sub" / "x.mp3")}, watch=music)
    monkeypatch.setattr(library, "device", lambda p: 2 if str(p).startswith(str(music)) else 1)
    r, state = run_file(env)
    assert r.path == str(music / "Sub" / "not_lossless" / "Artist - Song.aiff") or \
        r.path == str(music / "Sub" / "Artist - Song.aiff")
    assert (env.paths.root / "Superseded/Music/Sub/x.mp3").is_file()
    assert not any(p.name.startswith(".") for p in (music / "Sub").rglob("*"))
    ((_path, placed_by, codec, *_rest),) = file_facts_row(env)
    assert (placed_by, codec) == ("app", "pcm_s16be")
