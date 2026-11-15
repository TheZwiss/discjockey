"""Plans (issue 39 group V1.10, design §7.1): the store a dry run saves into and `--plan` runs from. The call path's
use of it (a dry run's `data.plan_id`, `--plan`, `needs_yes`) is in tests/test_cli_dryrun.py."""
import json
import os
from datetime import datetime, timedelta

import pytest

from discjockey.hub import plan_store
from discjockey.hub.plan_store import PlanExpired, UnknownPlan

ROOT = "/music/a"
ITEMS = {"t1": {"key": "t1", "action": "convert"}, "t2": {"key": "t2", "action": "rename"}}
NOW = datetime(2026, 11, 15, 12, 0, 0)


def test_the_same_dry_run_twice_is_the_same_plan(tmp_path):
    first = plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, {"command": "aiff convert"}, now=NOW)
    again = plan_store.save(tmp_path, "aiff convert", ROOT, dict(reversed(ITEMS.items())), now=NOW)
    assert first == again
    assert first.startswith("plan:") and len(first) == len("plan:") + 12
    assert sorted(p.name for p in (tmp_path / "plans").iterdir()) == [f"{first[5:]}.json"]  # one file, no temp left


def test_the_id_covers_kind_music_folder_and_item_keys(tmp_path):
    base = plan_store.plan_id("aiff convert", ROOT, ["t1", "t2"])
    assert base == plan_store.plan_id("aiff convert", ROOT, ["t2", "t1"])
    assert base != plan_store.plan_id("aiff rename", ROOT, ["t1", "t2"])
    assert base != plan_store.plan_id("aiff convert", "/music/b", ["t1", "t2"])
    assert base != plan_store.plan_id("aiff convert", ROOT, ["t1"])
    assert base != plan_store.plan_id("aiff convert", None, ["t1", "t2"])


def test_a_plan_loads_with_its_items_and_extra(tmp_path):
    identifier = plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, {"command": "aiff convert", "read": 7}, now=NOW)
    plan = plan_store.load(tmp_path, identifier, ROOT, now=NOW + timedelta(hours=23))
    assert (plan.id, plan.kind, plan.root, plan.created) == (identifier, "aiff convert", ROOT, NOW)
    assert plan.items == ITEMS and plan.extra["read"] == 7 and plan.command == "aiff convert"


def test_an_unknown_id_is_unknown_plan_whatever_it_looks_like(tmp_path):
    plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, now=NOW)
    for text in ("plan:0123456789ab", "plan:XYZ", "", "0123456789ab", "plan:../../etc/passwd", "plan:0123456789ab/..",
                 "plan:0123456789abc"):
        with pytest.raises(UnknownPlan) as e:
            plan_store.load(tmp_path, text, ROOT, now=NOW)
        assert e.value.reason == "unknown_id"


def test_a_file_that_is_not_a_plan_is_unknown(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "0123456789ab.json").write_text("not json")
    with pytest.raises(UnknownPlan):
        plan_store.load(tmp_path, "plan:0123456789ab", ROOT, now=NOW)
    (tmp_path / "plans" / "0123456789ab.json").write_text(json.dumps({"v": 1, "id": "plan:ffffffffffff"}))
    with pytest.raises(UnknownPlan):
        plan_store.load(tmp_path, "plan:0123456789ab", ROOT, now=NOW)


def test_a_plan_of_another_music_folder_has_expired_and_names_its_dry_run(tmp_path):
    identifier = plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, {"command": "aiff convert"}, now=NOW)
    with pytest.raises(PlanExpired) as e:
        plan_store.load(tmp_path, identifier, "/music/b", now=NOW)
    assert e.value.reason == "plan_expired" and "another music folder" in str(e.value)
    assert [n["run"] for n in e.value.next] == ["aiff convert --dry-run"]


def test_a_plan_is_good_for_24_hours(tmp_path):
    identifier = plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, {"command": "aiff convert"}, now=NOW)
    plan_store.load(tmp_path, identifier, ROOT, now=NOW + timedelta(hours=24))
    with pytest.raises(PlanExpired) as e:
        plan_store.load(tmp_path, identifier, ROOT, now=NOW + timedelta(hours=24, seconds=1))
    assert "more than a day old" in str(e.value) and e.value.next[0]["run"] == "aiff convert --dry-run"


def test_saving_prunes_plans_a_week_old_and_keeps_a_day_old_one_so_it_says_expired(tmp_path):
    old = plan_store.save(tmp_path, "aiff convert", ROOT, ITEMS, now=NOW)
    folder = tmp_path / "plans"
    long_ago = (NOW - timedelta(days=8)).timestamp()
    os.utime(folder / f"{old[5:]}.json", (long_ago, long_ago))
    day_old = plan_store.save(tmp_path, "aiff rename", ROOT, ITEMS, now=NOW - timedelta(days=1))
    os.utime(folder / f"{day_old[5:]}.json", ((NOW - timedelta(days=1)).timestamp(),) * 2)
    plan_store.save(tmp_path, "tidy run", ROOT, {"m1": {"key": "m1"}}, now=NOW)  # prunes
    with pytest.raises(UnknownPlan):
        plan_store.load(tmp_path, old, ROOT, now=NOW)
    with pytest.raises(PlanExpired):
        plan_store.load(tmp_path, day_old, ROOT, now=NOW + timedelta(hours=1))


def test_saving_writes_only_inside_plans(tmp_path):
    support = tmp_path / "support"
    support.mkdir()
    before = sorted(p.name for p in support.iterdir())
    plan_store.save(support, "aiff convert", ROOT, ITEMS, now=NOW)
    assert before == []
    assert [p.name for p in support.iterdir()] == ["plans"]


def test_bind_runs_what_still_stands_skips_what_changed_and_leaves_out_what_is_new(tmp_path):
    identifier = plan_store.save(tmp_path, "aiff convert", ROOT,
                                 {"a": {"key": "a", "action": "convert"}, "b": {"key": "b", "action": "rename"},
                                  "c": {"key": "c", "action": "convert"}}, now=NOW)
    plan = plan_store.load(tmp_path, identifier, ROOT, now=NOW)
    now = {"a": {"key": "a", "action": "convert"},      # the same
           "b": {"key": "b", "action": "convert"},      # its answer is another now
           "d": {"key": "d", "action": "convert"}}      # new since the plan; c is gone
    bound = plan_store.bind(plan, now)
    assert bound.run == ("a",) and bound.changed == ("b", "c") and bound.new == ("d",)


def test_the_items_of_a_dry_run_answer_are_its_keyed_rows():
    rows = [{"key": "a", "x": 1}, {"key": "b"}]
    assert plan_store.items_of({"items": rows}) == {"a": rows[0], "b": rows[1]}
    assert plan_store.items_of({"items": []}) == {}
    assert plan_store.items_of({"rows": rows}) is None                       # no `items`: a what-if, not a plan
    assert plan_store.items_of({"items": [{"key": "a"}, {"key": "a"}]}) is None  # a key names one item
    assert plan_store.items_of({"items": [{"name": "a"}]}) is None
    assert plan_store.items_of({"items": [{"key": 3}]}) is None
