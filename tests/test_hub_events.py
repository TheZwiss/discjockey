import dataclasses
import json

import pytest

from discjockey import events
from discjockey.hub import jobs
from discjockey.models import Action, SpotifyTrack

TRACK = SpotifyTrack("t1", "Gimme Gimme", ("Vatoz Locoz", "Other"), "Album", "https://i/x.jpg", 156000, "DE1")
ACTION = Action("move", "t1", "Hard_Bounce", TRACK, (0, 3), src="Library/A/x.aiff", dest_dir="Library/Hard_Bounce")
RESULT = events.Result("moved", "Hard_Bounce", "Vatoz Locoz", "Gimme Gimme", "t1", "from Library/A/x.aiff",
                       "lossless", "qobuz", None, "Library/Hard_Bounce/x.aiff", None)
SAMPLES = [
    events.RunStarted(3),
    events.ActionStarted(1, 3, ACTION),
    events.StepChanged("t1", "download"),
    events.Progress("t1", "download", 19.8e6, 31.0e6, "bytes"),
    events.Waiting("between", "Protection pause between Qobuz downloads", 34.0, 41.5),
    events.SourceChosen("t1", "qobuz", "isrc", "Gimme Gimme", 156.0),
    events.Checked("t1", 156.1, 156.0, "flac", True),
    events.AccountUsage("qobuz", 42, 80),
    events.ActionFinished(ACTION, RESULT),
    events.RunFinished(0, "/x/reports/2026-10-20_120000.md"),
    events.Message("info", "Reading your Spotify playlists..."),
    events.ReadingPlaylist(2, 7, "Powertrance"),
    jobs.JobStarted(7, "sync", None),
    jobs.JobFinished(7, "sync", True, None, "", {"exit_code": 0}),
    jobs.ConsoleBusy(True),
    jobs.FileDropped("t1", "Get Naughty (Extended Mix).wav", True, ""),
    jobs.SignInPhase("youtube", "waiting", "chrome", "Chrome"),
    jobs.AppUpdate("available", "1.0.0", "1.1.0", "https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0"),
]


def test_every_event_type_has_a_sample():
    assert {type(e) for e in SAMPLES} == set(jobs.EVENT_TYPES)


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_every_event_type_serialises_to_json(event):
    data = json.loads(jobs.event_json(event))
    assert data["type"] == type(event).__name__
    assert set(data) == {"type"} | {f.name for f in dataclasses.fields(event)}


def test_nested_records_become_plain_json():
    data = json.loads(jobs.event_json(events.ActionStarted(1, 3, ACTION)))
    assert data["action"]["track"]["artists"] == ["Vatoz Locoz", "Other"]
    assert data["action"]["order"] == [0, 3] and data["action"]["dest_dir"] == "Library/Hard_Bounce"
    finished = json.loads(jobs.event_json(events.ActionFinished(ACTION, RESULT)))
    assert finished["result"]["section"] == "moved" and finished["result"]["error_kind"] is None


def test_json_is_safe_inside_javascript():
    text = jobs.event_json(events.Message("info", "BΞNZ0 –   </script>"))
    assert text.isascii() and "</" not in text
    assert json.loads(text)["text"] == "BΞNZ0 –   </script>"
