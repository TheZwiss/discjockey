"""The convert→rename chain (plan stage D §1.2; coordinator's decision): Convert on an AIFF whose old file holds the
clean name lands on the song's ID (both files exist until rekordbox's commit), then the same call gives the file its
clean name (`rename.rename_file`, `after` = the Convert's result). Each step is journaled and crash-safe on its own;
the rename keeps the Convert's check and undo in its `before`, so two undos return the original file. Libraries in
tmp_path only (tests/convert_helpers.py, tests/rename_helpers.py)."""
from __future__ import annotations

import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import NOW, TID, PowerOff, file_facts_row, make_own, run_file, session, start_file_batch
from discjockey import audio, convert, library, rename, report, upgrades
from discjockey.library import load_state
from discjockey.rekordbox import anlz, master
from rekordbox_helpers import diff, dump
from rename_helpers import CLEAN, ID_NAME, batch_row, next_start, run_rename

pytestmark = needs_ffmpeg
STAMPS = {"rb_local_usn", "updated_at"}


def make_chain(tmp_path, monkeypatch, kind="aiff96", **kw):
    return make_own(tmp_path, monkeypatch, kind, entry={"path": CLEAN, "status": "lossless", "source_format": None},
                    **kw)


def row_of(env) -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = '1'")
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def test_an_aiff_24_96_at_its_clean_name_ends_at_the_clean_name_16_44(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)
    root = env.paths.root
    old = (root / CLEAN).read_bytes()
    r, state = run_file(env)
    assert (r.section, r.path) == ("converted", CLEAN)
    assert r.note.startswith(f"new file {CLEAN}, lined up with rekordbox; the old one moved to {env.superseded}")
    assert (root / env.superseded).read_bytes() == old and not (root / ID_NAME).exists()
    facts = audio.file_facts(root / CLEAN)
    assert (facts.sample_rate, facts.bits, facts.tags["title"]) == (44100, 16, "Song")
    e = load_state(env.paths)["tracks"][TID]
    assert e["path"] == CLEAN and state["pending"] == []
    check = e["rekordbox_check"]
    # the user's file kept its name and became an AIFF: the visible check is the Convert's; the rename is internal
    assert check["reason"] == "converted" and check["undo"]["kind"] == "rename" and check["undo"]["old"] == ID_NAME
    inner = check["undo"]["before"]["rekordbox_check"]  # the Convert's check, with its own undo
    assert inner["reason"] == "converted" and inner["undo"]["kind"] == "convert" and inner["undo"]["file"] == ID_NAME
    assert row_of(env)["FolderPath"] == str(root / CLEAN) and anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"
    ((path, placed_by, codec, rate, bits, _k),) = file_facts_row(env)
    assert (path, placed_by, codec, rate, bits) == ("A/Artist - Song.aiff", "app", "pcm_s16be", 44100, 16)
    assert upgrades.can_undo(e) and report.check_text(check) == report.CONVERTED_CHECK


def test_the_chain_says_converted_everywhere_and_carries_the_converts_kept_edits(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch, row={"Title": "My Edit Name"})
    r, state = run_file(env)
    kept = state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"]
    words = f"Kept your own {' / '.join(kept)} in rekordbox."
    assert "title" in kept and r.section == "converted" and r.note.endswith(words)
    check = state["tracks"][TID]["rekordbox_check"]
    assert (check["reason"], check["rekordbox"]) == ("converted", {"entries": ["1"], "kept": kept})
    assert "renamed" not in r.note and report.RENAMED_CHECK not in report.check_text(check)
    assert row_of(env)["Title"] == "My Edit Name"  # the rename wrote identity only
    state = load_state(env.paths)
    upgrades.undo(env.paths, state, TID)  # the rename's undo brings the Convert's own check back
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == kept


def test_the_clean_up_keeps_the_backup_the_nested_undo_names(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)
    run_file(env)
    state = load_state(env.paths)
    outer = state["tracks"][TID]["rekordbox_check"]["undo"]
    inner = outer["before"]["rekordbox_check"]["undo"]
    inner["backup"] = "only-the-convert-has-this-one"  # as if the two steps had run in two sessions
    kept = []
    monkeypatch.setattr("discjockey.rekordbox.backup.prune", lambda paths, keep: kept.append(set(keep)))
    library._prune_undo(env.paths, state)
    assert outer["backup"] in kept[0] and inner["backup"] in kept[0]


def test_undo_twice_restores_the_original_name_bytes_and_rekordbox_rows(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)
    music, rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    facts, entry = file_facts_row(env), load_state(env.paths)["tracks"][TID]
    run_file(env)
    state = load_state(env.paths)
    first = upgrades.undo(env.paths, state, TID)  # the rename
    assert first.section == "upgrade_undone" and first.path == ID_NAME
    e = state["tracks"][TID]
    assert e["path"] == ID_NAME and e["rekordbox_check"]["reason"] == "converted" and upgrades.can_undo(e)
    assert row_of(env)["FolderPath"] == str(env.paths.root / ID_NAME)
    assert (env.paths.root / ID_NAME).is_file() and not (env.paths.root / CLEAN).exists()
    second = upgrades.undo(env.paths, state, TID)  # the convert
    assert second.path == CLEAN
    assert env.music() == music and env.anlz_files() == analysis
    for table, _id, column, old, new in diff(rows, dump(env.place.db)):
        assert column in STAMPS or table in {"agentRegistry", "djmdArtist", "djmdAlbum", "djmdLabel"}, (table, column)
    now = load_state(env.paths)
    assert state["pending"] == [] and now["pending"] == [] and file_facts_row(env) == facts
    assert {k: now["tracks"][TID].get(k) for k in entry} == entry
    assert not upgrades.can_undo(now["tracks"][TID])  # nothing left to undo


def test_the_wrong_tags_aiff_16_44_takes_the_same_way(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch, "aiff")
    old = (env.paths.root / CLEAN).read_bytes()
    r, _state = run_file(env)
    assert r.path == CLEAN and (env.paths.root / env.superseded).read_bytes() == old


def test_the_batch_item_ends_with_the_final_name(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)
    batch = start_file_batch(env)
    r, _state = run_file(env, batch=(batch, 0))
    (item,) = batch_row(env, batch).items
    assert item.state == "done" and item.result["path"] == CLEAN and item.result["note"] == r.note
    assert load_state(env.paths)["tracks"][TID]["rekordbox_check"]["batch"] == batch


def test_a_file_rekordbox_does_not_have_is_converted_and_renamed_without_it(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch, holds_file=False)
    rows = dump(env.place.db)
    r, _state = run_file(env)
    assert r.path == CLEAN and r.note.count(convert.NO_TRACK_NOTE) == 1 and dump(env.place.db) == rows
    assert report.check_text(load_state(env.paths)["tracks"][TID]["rekordbox_check"]) == report.CONVERTED_NO_TRACK_CHECK


def test_a_crash_between_the_steps_leaves_a_valid_aiff_with_the_id_name(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)

    def dies(*a, **k):
        raise PowerOff
    with monkeypatch.context() as m:
        m.setattr(rename, "rename_file", dies)
        with pytest.raises(PowerOff):
            run_file(env)
    messages, state = next_start(env)
    assert messages == [] and state["pending"] == []
    e = load_state(env.paths)["tracks"][TID]
    assert e["path"] == ID_NAME and e["rekordbox_check"]["reason"] == "converted"
    assert audio.file_facts(env.paths.root / ID_NAME).sample_rate == 44100 and row_of(env)["FolderPath"].endswith(ID_NAME)
    r, state = run_rename(env)  # the next run renames it; a rename on its own is one step back only
    assert r.path == CLEAN
    assert "undo" not in state["tracks"][TID]["rekordbox_check"]["undo"]["before"]["rekordbox_check"]


def test_a_rename_that_cannot_run_leaves_the_convert_standing_and_says_so(tmp_path, monkeypatch):
    env = make_chain(tmp_path, monkeypatch)

    def refuses(*a, **k):
        raise rename.blocked("cloud")
    monkeypatch.setattr(rename, "rename_file", refuses)
    r, state = run_file(env)
    assert (r.section, r.path) == ("converted", ID_NAME)
    assert "The file keeps the name Artist - Song [t1aaaa].aiff for now: " in r.note and "Cloud Library Sync" in r.note
    assert state["tracks"][TID]["path"] == ID_NAME and state["pending"] == []


def cut_rename_at_mark(m, number):
    """The Mac goes off right after the rename step's `number`th journal mark (only its own: the Convert's are
    convert.mark_op's): 2 = the file placed, 3 = rekordbox committed."""
    def die(*a, **k):
        raise PowerOff
    for name in ("_drop", "_roll_back", "_settle"):
        m.setattr(rename, name, die)
    real, calls = rename.mark_op, {"n": 0}

    def mark(paths, state, op):
        real(paths, state, op)
        calls["n"] += 1
        if calls["n"] == number:
            raise PowerOff
    m.setattr(rename, "mark_op", mark)


@pytest.mark.parametrize("at, done", [(2, False), (3, True)])
def test_a_crash_inside_the_rename_is_recovered_and_keeps_the_converts_undo(tmp_path, monkeypatch, at, done):
    env = make_chain(tmp_path, monkeypatch)
    with monkeypatch.context() as m:
        cut_rename_at_mark(m, at)
        with pytest.raises(PowerOff):
            run_file(env)
    messages, _state = next_start(env)
    now = load_state(env.paths)["tracks"][TID]
    if done:
        assert messages == [(rename.FINISHED.format(name="Artist - Song"), True)]
        assert now["path"] == CLEAN
        assert now["rekordbox_check"]["undo"]["before"]["rekordbox_check"]["undo"]["kind"] == "convert"
    else:
        assert messages == [(rename.NOT_FINISHED.format(name="Artist - Song"), False)]
        assert now["path"] == ID_NAME and now["rekordbox_check"]["reason"] == "converted"
