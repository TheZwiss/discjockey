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
