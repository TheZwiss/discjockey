"""The recorded event streams the window's tests replay, and the JSON schema of every event."""
import importlib.util
import json
from pathlib import Path

import pytest
from audio_helpers import needs_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("record_hub_events", ROOT / "scripts" / "record_hub_events.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA = json.loads((FIXTURES / "hub_events.schema.json").read_text())


def lines(name):
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines()]


def valid(value, schema, defs) -> bool:
    if "$ref" in schema:
        return valid(value, defs[schema["$ref"].split("/")[-1]], defs)
    if "const" in schema:
        return value == schema["const"]
    if "anyOf" in schema:
        return any(valid(value, s, defs) for s in schema["anyOf"])
    if "oneOf" in schema:
        return sum(valid(value, s, defs) for s in schema["oneOf"]) == 1
    kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    checks = {"null": value is None, "boolean": isinstance(value, bool), "string": isinstance(value, str),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "number": isinstance(value, (int, float)) and not isinstance(value, bool),
              "object": isinstance(value, dict), "array": isinstance(value, list)}
    if not any(checks[k] for k in kinds):
        return False
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        return set(value) == set(props) and all(valid(value[k], props[k], defs) for k in props)
    if isinstance(value, list) and "items" in schema:
        return all(valid(v, schema["items"], defs) for v in value)
    return True


def test_the_schema_is_up_to_date():
    assert script.event_schema() == SCHEMA  # a renamed field breaks this (rerun the script and update the UI)


@pytest.mark.parametrize("name", ["hub_events_sync.jsonl", "hub_events_stopped.jsonl"])
def test_every_recorded_event_fits_the_schema(name):
    for event in lines(name):
        assert valid(event, SCHEMA, SCHEMA["$defs"]), event


def test_the_full_sync_shows_every_kind_of_moment():
    events = lines("hub_events_sync.jsonl")
    types = {e["type"] for e in events}
    assert types >= {"JobStarted", "JobFinished", "RunStarted", "ActionStarted", "StepChanged", "Progress", "Waiting",
                     "SourceChosen", "Checked", "AccountUsage", "ActionFinished", "RunFinished", "Message"}
    sections = [e["result"]["section"] for e in events if e["type"] == "ActionFinished"]
    assert sections == ["moved", "new_lossless", "missing", "new_not_lossless", "errors", "upgrade_ready"]
    errors = [e["result"] for e in events if e["type"] == "ActionFinished" and e["result"]["section"] == "errors"]
    assert errors[0]["error_kind"] == "network"
    assert {e["kind"] for e in events if e["type"] == "Waiting"} >= {"search", "between"}
    assert {e["unit"] for e in events if e["type"] == "Progress"} == {"bytes", "seconds"}
    assert "/tmp" not in (FIXTURES / "hub_events_sync.jsonl").read_text()


def test_the_stopped_sync_ends_with_130():
    events = lines("hub_events_stopped.jsonl")
    assert [e["exit_code"] for e in events if e["type"] == "RunFinished"] == [130]
    assert events[-1]["type"] == "JobFinished" and events[-1]["result"]["exit_code"] == 130


def collapse(events):
    out = []
    for e in events:
        key = (e["type"], e.get("result", {}).get("section"))
        if not out or out[-1] != key:
            out.append(key)
    return out


@needs_ffmpeg
def test_the_fixture_comes_from_the_current_code(tmp_path):
    fresh = [json.loads(line) for line in script.record(tmp_path)]
    assert collapse(fresh) == collapse(lines("hub_events_sync.jsonl"))
