"""The rehearsal script's guards on its work folder (scripts/rekordbox_rehearsal.py; plan stage B §7 RH): it never
works in or around the rekordbox folder, and the steps that delete inside the work folder need the mark `copy-db`
leaves. Nothing here touches a real library: `copy_db` runs on a fake `master.db` in a temp folder."""
from __future__ import annotations

import importlib.util

import pytest

from discjockey import REPO


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("rekordbox_rehearsal", REPO / "scripts" / "rekordbox_rehearsal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_work_folder_inside_or_around_the_rekordbox_folder_is_refused(script, tmp_path):
    source = tmp_path / "Pioneer" / "rekordbox"
    source.mkdir(parents=True)
    for work in (source, source / "work", tmp_path / "Pioneer", tmp_path):
        with pytest.raises(script.Refused, match="separate folders"):
            script.check_work(work, source)
    assert script.check_work(tmp_path / "work", source) == (tmp_path / "work").resolve()


def test_the_steps_that_delete_need_the_mark_copy_db_leaves(script, tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "support").mkdir(parents=True)
    keep = work / "support" / "precious.txt"
    keep.write_text("not a rehearsal's", encoding="utf-8")
    for step in (lambda: script.rehearse(work, None), lambda: script.copy_tracks(tmp_path / "rb", work, ["a=1"])):
        with pytest.raises(script.Refused, match="copy-db"):
            step()
    assert keep.exists()

    source = tmp_path / "rb"
    source.mkdir()
    (source / "master.db").write_bytes(b"not a real library")
    monkeypatch.setattr(script.process, "running", lambda: False)
    assert script.copy_db(source, tmp_path / "fresh") == 0
    script.need_marker(tmp_path / "fresh")


def test_rehearse_sync_needs_the_mark_and_a_fresh_work_folder(script, tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "support").mkdir(parents=True)
    with pytest.raises(script.Refused, match="copy-db"):
        script.rehearse_sync(work, "MP3 #1")
    (work / script.MARKER).write_text("", encoding="utf-8")
    (work / "picks.json").write_text('[{"label": "M4A 44.1 #1"}, {"label": "MP3 #1"}]', encoding="utf-8")
    (work / "source").mkdir()
    (work / "source" / "master.db").write_bytes(b"not a real library")
    monkeypatch.setattr(script.process, "running", lambda: False)
    for label in ("M4A 44.1 #1", "MP3 #9"):  # not an MP3 / not a pick
        with pytest.raises(script.Refused, match="label of one of the MP3 tracks"):
            script.rehearse_sync(work, label)
    (work / script.SYNC_MARK).write_text("", encoding="utf-8")
    with pytest.raises(script.Refused, match="ran in this work folder already"):
        script.rehearse_sync(work, "MP3 #1")
    assert (work / "support").is_dir()  # nothing was deleted


def test_the_rehearsal_playlists_line_reads_nothing(script, tmp_path):
    """A playlists.txt needs an active line, and this one is Liked music while Settings' choice is off: left out
    before any request, so the rehearsal's sync reads no playlist and needs no login."""
    paths = script.Paths(tmp_path / "music", support=tmp_path / "support")
    lines = script.config.parse_playlists(script.PLAYLISTS)
    assert len(lines) == 1
    assert script.sources.left_out(paths, lines[0])


def test_a_real_sync_runs_only_after_a_dry_run_planned_no_action(script, tmp_path, monkeypatch):
    calls = []

    def fake_cli(work, tag, *args, offline=False):
        calls.append((tag, args, offline))
        return 0, {"counts": {"upgrade": 1}}, "", 0.1

    monkeypatch.setattr(script, "run_cli", fake_cli)
    with pytest.raises(script.Refused, match="no real run"):
        script.real_sync(tmp_path, "rh9-sync")
    assert calls == [("rh9-sync-guard", ("--dry-run", "--json"), True)]
    monkeypatch.setattr(script, "run_cli", lambda work, tag, *args, offline=False: (calls.append(tag), (0, {}, "", 0.1))[1])
    calls.clear()
    script.real_sync(tmp_path, "rh9-sync")
    assert calls == ["rh9-sync-guard", "rh9-sync"]


def test_rehearse_convert_needs_the_mark_the_right_picks_and_a_fresh_work_folder(script, tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "support").mkdir(parents=True)
    with pytest.raises(script.Refused, match="copy-db"):
        script.rehearse_convert(work)
    (work / script.MARKER).write_text("", encoding="utf-8")
    (work / "source").mkdir()
    (work / "source" / "master.db").write_bytes(b"not a real library")
    monkeypatch.setattr(script.process, "running", lambda: False)
    (work / "picks.json").write_text('[{"label": "MP3 #1"}]', encoding="utf-8")
    with pytest.raises(script.Refused, match="needs exactly these picks"):
        script.rehearse_convert(work)
    labels = [script.PCM, *script.LOSSY_SET]
    (work / "picks.json").write_text("[" + ", ".join(f'{{"label": "{x}"}}' for x in labels) + "]", encoding="utf-8")
    (work / script.CONVERT_MARK).write_text("", encoding="utf-8")
    with pytest.raises(script.Refused, match="ran in this work folder already"):
        script.rehearse_convert(work)
    assert (work / "support").is_dir()  # nothing was deleted


def test_the_samples_helpers_find_the_shift_the_render_makes(script):
    rng = script.np.random.default_rng(1)
    old = rng.integers(-20000, 20000, size=(900_000, 2), dtype="<i2")
    for d in (0, 37, -12):
        new = script.shifted(old, d)
        assert len(new) == len(old) + max(d, 0) + min(d, 0)
        lag, score = script.lag_of(old, new)
        assert (lag, round(score, 3)) == (d, 1.0)
    assert not script.np.array_equal(script.shifted(old, 3), script.shifted(old, 4)[:len(old) + 3])
