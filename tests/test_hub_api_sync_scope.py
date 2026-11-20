"""The Sync scope in settings.json (issue 39 V2.5b): `sync_scope()` reads it, `set_sync_scope(on, off)` is a settings
job. The window's switches and an agent's `sync scope` commands go through the same two methods, so a new `HubApi` (another
process) sees what one saved."""
from __future__ import annotations

import json

import pytest

from discjockey.settings import Settings, load_settings, save_settings
from hub_helpers import ID1, ID2, make_api, make_root, make_unbound_api, wait_job, window

BOUNCE = f"playlist:{ID1}"
TRANCE = f"playlist:{ID2}"
HARD = "folder:Library/Hard_Bounce"


def test_nothing_is_left_out_until_a_switch_is_turned_off(tmp_path):
    api, _ = make_api(make_root(tmp_path))
    assert api.sync_scope() == {"ok": True, "off": [], "weekly_off": []}


def test_off_adds_in_order_names_them_and_on_takes_them_back(tmp_path):
    paths = make_root(tmp_path)
    api, rec = make_api(paths)
    f = wait_job(api, rec, api.set_sync_scope([], [TRANCE, "kind:weekly", HARD]))
    assert (f.ok, f.kind) == (True, "set_sync_scope")
    want = {"off": [{"target": TRANCE, "name": "Powertrance"}, {"target": HARD, "name": "Hard_Bounce"}],
            "weekly_off": [{"kind": "weekly", "label": "Weekly checks"}]}
    assert f.result == want
    assert {k: v for k, v in api.sync_scope().items() if k != "ok"} == want
    s = load_settings(paths.settings_file)
    assert (s.scope_off, s.weekly_off) == ((TRANCE, HARD), ("weekly",))
    # more off: order kept, a repeat is not listed twice
    wait_job(api, rec, api.set_sync_scope([], [BOUNCE, TRANCE, "kind:retry"]))
    s = load_settings(paths.settings_file)
    assert (s.scope_off, s.weekly_off) == ((TRANCE, HARD, BOUNCE), ("weekly", "retry"))
    # on takes back (an item that was never off is no problem)
    f = wait_job(api, rec, api.set_sync_scope([HARD, "kind:weekly", "kind:retry", "folder:Library/Never"], []))
    assert [c["target"] for c in f.result["off"]] == [TRANCE, BOUNCE] and f.result["weekly_off"] == []
    assert load_settings(paths.settings_file).scope_off == (TRANCE, BOUNCE)


def test_a_target_nothing_has_any_more_stays_listed_under_its_target(tmp_path):
    api, rec = make_api(make_root(tmp_path))
    f = wait_job(api, rec, api.set_sync_scope([], ["playlist:spotify:gone", "folder:/Volumes/Away/Crate/"]))
    assert f.result["off"] == [{"target": "playlist:spotify:gone", "name": "playlist:spotify:gone"},
                               {"target": "folder:/Volumes/Away/Crate/", "name": "Crate"}]


def test_a_new_hub_sees_the_scope_another_one_saved(tmp_path):
    paths = make_root(tmp_path)
    one, rec = make_api(paths)
    assert wait_job(one, rec, one.set_sync_scope([], [BOUNCE, "kind:retry"])).ok
    two, _ = make_api(paths)
    seen = two.sync_scope()
    assert [c["target"] for c in seen["off"]] == [BOUNCE] and seen["off"][0]["name"] == "Hard_Bounce"
    assert seen["weekly_off"] == [{"kind": "retry", "label": "Not found last time"}]


@pytest.mark.parametrize("on, off, word", [
    ([], ["bogus"], "bogus"), (["kind:new"], [], "kind:new"), ([], ["folder:"], "folder:"), ([], [3], "3"),
    ([HARD], [HARD], HARD), (["kind:weekly"], ["kind:weekly"], "kind:weekly")])
def test_a_bad_item_or_one_in_both_lists_is_refused_before_a_job_and_changes_nothing(tmp_path, on, off, word):
    paths = make_root(tmp_path)
    api, rec = make_api(paths)
    answer = api.set_sync_scope(on, off)
    assert window(answer)["kind"] == "refused" and word in window(answer)["message"]
    assert not paths.settings_file.exists() and api._jobs.current is None


def test_the_lists_must_be_lists(tmp_path):
    api, _ = make_api(make_root(tmp_path))
    assert window(api.set_sync_scope(None, []))["kind"] == "refused"
    assert window(api.set_sync_scope([], "kind:weekly"))["kind"] == "refused"


def test_a_scope_write_keeps_every_other_setting(tmp_path):
    paths = make_root(tmp_path)
    save_settings(paths.settings_file, Settings(daily_qobuz_limit=40, qobuz_skipped=True, auto_upgrade=False))
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.set_sync_scope([], [HARD])).ok
    s = load_settings(paths.settings_file)
    assert (s.daily_qobuz_limit, s.qobuz_skipped, s.auto_upgrade, s.scope_off) == (40, True, False, (HARD,))
    assert json.loads(paths.settings_file.read_text())["sync_scope"] == {"off": [HARD], "weekly_off": []}


def test_the_scope_works_with_no_music_folder(tmp_path):
    api, rec = make_unbound_api(tmp_path / "support")
    assert api.sync_scope() == {"ok": True, "off": [], "weekly_off": []}
    f = wait_job(api, rec, api.set_sync_scope([], ["kind:retry", HARD]))
    assert f.ok and f.result["off"] == [{"target": HARD, "name": "Hard_Bounce"}]
    assert api.sync_scope()["weekly_off"] == [{"kind": "retry", "label": "Not found last time"}]


def test_a_settings_file_that_cannot_be_read_shows_everything_on_and_refuses_the_write(tmp_path):
    paths = make_root(tmp_path)
    paths.settings_file.write_text('{"auto_upgrade": "yes"}')
    api, rec = make_api(paths)
    assert api.sync_scope()["off"] == []
    f = wait_job(api, rec, api.set_sync_scope([], [HARD]))
    assert not f.ok and paths.settings_file.read_text() == '{"auto_upgrade": "yes"}'
