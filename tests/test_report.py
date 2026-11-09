import json
from datetime import datetime

import pytest

from discjockey.events import Result
from discjockey.library import Paths
from discjockey.models import Action, Plan, SourceTrack
from discjockey.report import (
    SECTIONS, RunLog, check_text, render_line, render_not_lossless, render_plan, render_report, summary, upgrades_waiting,
    write_not_lossless,
    write_run,
)

STARTED = datetime(2026, 10, 20, 21, 5, 9)
FINISHED = datetime(2026, 10, 20, 22, 0, 0)


def test_report_sections_only_when_not_empty():
    log = RunLog(STARTED)
    log.add(Result("new_lossless", "Hard_Bounce", "Artist", "Song", "t1", "Qobuz FLAC · verified lossless"))
    log.add_text("skipped", "[Hard_Bounce] Local song (local file, not on Spotify)")
    text = render_report(log, FINISHED)
    assert "## New lossless tracks (1)" in text
    assert "- [Hard_Bounce] Artist - Song — Qobuz FLAC · verified lossless — https://open.spotify.com/track/t1" in text
    assert "- [Hard_Bounce] Local song (local file, not on Spotify)" in text
    assert "## Skipped playlist items (1)" in text  # Spotify's local files and Qobuz's "no Qobuz ID" entries alike
    assert "Moved" not in text


def test_run_files_have_seconds_and_a_json_twin(tmp_path):
    log = RunLog(STARTED)
    log.add(Result("missing", "A", "Artist", "Gone", "t2", status="missing"))
    md = write_run(Paths(tmp_path, support=tmp_path / ".support"), log, FINISHED, exit_code=0)
    assert md.name == "2026-10-20_210509.md"
    data = json.loads(md.with_suffix(".json").read_text())
    assert data["exit_code"] == 0 and data["finished"] == "2026-10-20T22:00:00"
    assert data["results"][0]["section"] == "missing" and data["results"][0]["status"] == "missing"


def test_empty_run_says_nothing_happened(tmp_path):
    md = write_run(Paths(tmp_path, support=tmp_path / ".support"), RunLog(STARTED), FINISHED, exit_code=0)
    assert "Nothing happened" in md.read_text()


def entry(status, folder="A", in_playlists=True, **kw):
    e = {"artist": "Artist", "title": "Song", "folder": folder, "status": status, "source": None,
         "cutoff_hz": None, "in_playlists": in_playlists}
    e.update(kw)
    return e


def test_not_lossless_md_groups_and_filters():
    state = {"tracks": {
        "t1": entry("not_lossless", source="youtube_music", cutoff_hz=20000),
        "t2": entry("missing", folder="B", title="Gone"),
        "t3": entry("lossless"),
        "t4": entry("missing", in_playlists=False, title="Dropped"),
    }}
    text = render_not_lossless(state)
    assert text.index("## A") < text.index("## B")
    assert "not lossless, from YouTube Music, cutoff 20.0 kHz" in text
    assert "`Library/B/Artist - Gone.wav`" in text
    assert "beatport.com/search?q=Artist+Gone" in text
    assert "Dropped" not in text and "t3" not in text


def test_not_lossless_md_when_everything_is_lossless(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    write_not_lossless(paths, {"tracks": {"t1": entry("lossless")}})
    assert "Every track in your playlists is lossless" in paths.not_lossless_md.read_text()


def act(kind, id, reason="", **kw):
    return Action(kind, id, "A", SourceTrack(id, f"Song {id}", ("Artist",), "Al", None, 1, None), (0, 0),
                  reason=reason, **kw)


def test_render_plan_counts_and_truncates():
    actions = [act("acquire", f"t{i}", reason="new") for i in range(25)] + [
        act("adopt_bought", "m1", src="Library/A/Artist - Song m1.wav")]
    text = render_plan(Plan({"tracks": {}}, actions, [], [], []), full=False)
    assert "Download (new): 25" in text and "... and 5 more" in text
    assert "Add a bought file: 1" in text and "[A] Artist - Song m1" in text
    assert "... and" not in render_plan(Plan({"tracks": {}}, actions, [], [], []), full=True)


def test_a_song_of_the_users_own_is_labelled_your_music():
    own = SourceTrack("1", "Night Drive", ("Example Artist",), "", None, 200000, None, service="local")
    plan = Plan({"tracks": {}}, [Action("upgrade", "local:1", "", own, (1, 0))], [], [], [])
    text = render_plan(plan, full=True)
    assert "    [your music] Example Artist - Night Drive" in text and "[]" not in text
    line = render_line(Result("checked", "", "Example Artist", "Night Drive", "local:1", "no better version yet"))
    assert line == "- [your music] Example Artist - Night Drive — no better version yet"
    assert render_line(Result("checked", "A", "Artist", "Song", "t1")).startswith("- [A] Artist - Song")


def test_the_plan_names_an_own_songs_folder_as_its_run_report_does():
    """The dry run's lines file an own song under the folder its file sits in, as the run report does (result_folder,
    leftovers C2): "your music" only when that can't be told."""
    own = SourceTrack("1", "Night Drive", ("Example Artist",), "", None, 200000, None, service="local")
    action = Action("upgrade", "local:1", "", own, (1, 0))
    state = {"tracks": {"local:1": {"path": "/Users/dj/Music/Rekordbox/Hard/Night Drive.mp3"}}}
    where = {"/Users/dj/Music/Rekordbox/Hard/Night Drive.mp3": "Rekordbox › Hard"}.get
    text = render_plan(Plan(state, [action], [], [], []), full=True, where=lambda p: where(p) or "")
    assert "    [Rekordbox › Hard] Example Artist - Night Drive" in text and "your music" not in text
    unknown = render_plan(Plan(state, [action], [], [], []), full=True, where=lambda p: "")
    assert "    [your music] Example Artist - Night Drive" in unknown
    pl = act("acquire", "t1", reason="new")  # a playlist song keeps its playlist folder, whatever `where` says
    assert f"    [{pl.folder}] " in render_plan(Plan({"tracks": {}}, [pl], [], [], []), full=True, where=lambda p: "X")


def test_render_plan_up_to_date():
    assert "up to date" in render_plan(Plan({"tracks": {}}, [], [], [], []), full=False)


def test_parked_upgrades_are_listed_near_the_top_of_the_report():
    keys = [k for k, _ in SECTIONS]
    assert keys.index("upgrade_ready") < keys.index("checked") and "upgraded" not in keys
    log = RunLog(STARTED)
    log.add(Result("upgrade_ready", "A", "Artist", "Song", "t1", "matches exactly · waiting in Upgrades ready/A/x.aiff"))
    assert "## Better version found, waiting for you (run discjockey upgrades) (1)" in render_report(log, FINISHED)


def test_not_lossless_md_says_when_a_lossless_version_is_ready():
    up = {"file": "Upgrades ready/A/Artist - Song.aiff", "alignment": {"result": "exact", "text": "matches exactly"}}
    text = render_not_lossless({"tracks": {"t1": entry("not_lossless", source="youtube_music", upgrade=up),
                                           "t2": entry("not_lossless", title="Other")}})
    assert text.count("Better version ready") == 1
    assert "  - Better version ready: run `discjockey upgrades` (matches exactly)" in text


def test_summary_points_to_waiting_upgrades(tmp_path):
    state = {"tracks": {"t1": entry("not_lossless", upgrade={"file": "x"}), "t2": entry("not_lossless"),
                        "t3": entry("not_lossless", upgrade={"file": "y"})}}
    assert upgrades_waiting(state) == 2
    text = summary(RunLog(STARTED), tmp_path / "r.md", upgrades_waiting(state))
    assert text.endswith("2 better versions are ready: run `discjockey upgrades`.")
    assert "ready" not in summary(RunLog(STARTED), tmp_path / "r.md")


def test_not_lossless_md_keeps_hidden_tracks_and_marks_them():
    state = {"tracks": {"t1": entry("not_lossless", source="youtube_music", cutoff_hz=16000, hidden=True),
                        "t2": entry("missing", title="Gone")}}
    text = render_not_lossless(state)
    assert "**Artist - Song** (hidden) (not lossless" in text
    assert "**Artist - Gone** (not found" in text


def test_report_and_summary_list_the_tracks_to_check_in_rekordbox(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    state = {"tracks": {"t1": entry("lossless", rekordbox_check={"reason": "added_as_new", "since": "2026-10-16"}),
                        "t2": entry("lossless")}}
    log = RunLog(STARTED)
    md = write_run(paths, log, STARTED, 0, state)
    text = md.read_text()
    assert "## Check in rekordbox (1)" in text and "set the cues again" in text
    assert json.loads(md.with_suffix(".json").read_text())["results"][0]["section"] == "rekordbox_check"
    out = summary(log, md)
    assert "1 track to check in rekordbox (see the report)" in out and "Check in rekordbox:" not in out
    assert "check in rekordbox" not in summary(RunLog(STARTED), md)


ALIGNED = ("This is the same edit, lined up with your old file to the sample. In rekordbox: relocate your old track to "
           "the new file (right-click › Relocate); its cues fit exactly.")


@pytest.mark.parametrize("check,text", [
    ({"reason": "added_as_new", "since": "2026-10-16", "match": "exact", "offset_ms": 0.0},
     "This is the same edit. In rekordbox: relocate the old entry to the new file, its cues fit."),
    ({"reason": "added_as_new", "since": "2026-10-16", "match": "shifted", "offset_ms": -23.0},
     "This is the same edit, 23 ms apart. In rekordbox: relocate the old entry to the new file, its cues fit to "
     "within 23 ms."),
    ({"reason": "added_as_new", "since": "2026-11-08", "match": "exact", "offset_ms": 0.0, "aligned": True},
     ALIGNED),
    ({"reason": "added_as_new", "since": "2026-11-08", "match": "shifted", "offset_ms": -23.0, "aligned": True},
     ALIGNED),  # lined up to the sample: no "within N ms" any more
    ({"reason": "added_as_new", "since": "2026-11-08", "match": "exact", "offset_ms": 0.0, "aligned": False},
     "This is the same edit. In rekordbox: relocate the old entry to the new file, its cues fit."),
    ({"reason": "added_as_new", "since": "2026-11-08", "match": "shifted", "offset_ms": 12.0, "aligned": False},
     "This is the same edit, 12 ms apart. In rekordbox: relocate the old entry to the new file, its cues fit to "
     "within 12 ms."),  # rekordbox's timing was unknown: renamed as before, today's words
    ({"reason": "added_as_new", "since": "2026-11-08", "match": "different", "offset_ms": 0.0, "aligned": True},
     "This is a different edit. In rekordbox: analyse it again and set the cues again."),
    ({"reason": "added_as_new", "since": "2026-10-16", "match": "different", "offset_ms": 0.0},
     "This is a different edit. In rekordbox: analyse it again and set the cues again."),
    ({"reason": "added_as_new", "since": "2026-10-16", "match": "unknown", "offset_ms": 0.0},
     "This is a different edit. In rekordbox: analyse it again and set the cues again."),
    ({"reason": "added_as_new", "since": "2026-10-16"},  # a record from before the measurement was kept
     "This is a different edit. In rekordbox: analyse it again and set the cues again."),
    ({"reason": "wrong_song", "since": "2026-10-16", "match": "exact"},  # the measurement only belongs to added_as_new
     "This track now plays the right song. In rekordbox: analyse it again and delete the old cues (they belong to "
     "the wrong song)."),
    ({"reason": "other"}, "Check this track in rekordbox."),
    # stage B: a swap whose rekordbox text Discjockey wrote needs no Reload Tag; one whose write didn't run keeps it
    ({"reason": "swapped", "reload_tag": False},
     "The lossless audio is in your file, so rekordbox keeps its cues, and Discjockey updated its names in rekordbox. "
     "In rekordbox: analyse it again so the waveform shows the full sound."),
    ({"reason": "swapped", "reload_tag": False, "moved": True},
     "The lossless audio is in your file, which moved up out of not_lossless/, and Discjockey updated its names in "
     "rekordbox. In rekordbox: Auto Relocate finds it by its name with its cues, then analyse it again."),
    ({"reason": "swapped", "reload_tag": True},
     "The lossless audio is in your file, so rekordbox keeps its cues. In rekordbox: Reload Tag, and analyse it "
     "again so the waveform shows the full sound."),
    ({"reason": "repointed", "rekordbox": {"entries": ["1"], "kept": []}},  # design §8's words
     "The better audio is in a new AIFF with a clean name, and your rekordbox track plays it with its cues, "
     "playlists and history. In rekordbox, analyse it again so the waveform shows the full sound (lock the beatgrid "
     "first if you set it by hand)."),
    ({"reason": "repointed", "rekordbox": None},
     "The better audio is in a new AIFF with a clean name. This file isn't in your rekordbox collection, so there "
     "was nothing to keep there."),
])
def test_check_text_words_the_check_by_what_the_files_measured_as(check, text):
    assert check_text(check) == text


def test_not_lossless_md_lists_bitrate_and_free_downloads():
    gate = {"url": "https://hypeddit.com/a/b", "host": "hypeddit.com", "direct": False, "title": "Song (Free DL)",
            "uploader": "DJ X"}
    text = render_not_lossless({"tracks": {"t1": entry("not_lossless", source="soundcloud", cutoff_hz=17900,
                                                       source_kbps=160, free_downloads=[gate])}})
    assert "not lossless, from SoundCloud, 160 kbps, cutoff 17.9 kHz" in text
    assert "  - Free download from the artist on hypeddit.com: [Song (Free DL)](https://hypeddit.com/a/b) " \
           "(uploaded by DJ X)" in text


def test_links_follow_the_tracks_service():
    log = RunLog(STARTED)
    log.add(Result("new_lossless", "A", "Artist", "Song", "qobuz:900000001", "Qobuz FLAC"))
    log.add(Result("missing", "A", "Artist", "Other", "youtube:1"))  # a service whose links can't be derived from an id
    log.add(Result("missing", "A", "Artist", "Third", "soundcloud:900000101"))
    text = render_report(log, FINISHED)
    assert "Qobuz FLAC — https://open.qobuz.com/track/900000001" in text
    assert "- [A] Artist - Third — https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900000101" in text
    assert "- [A] Artist - Other\n" in text and "spotify.com" not in text
    state = {"tracks": {"qobuz:900000001": entry("missing", title="Gone")}}
    assert "· [Qobuz](https://open.qobuz.com/track/900000001) · [Beatport]" in render_not_lossless(state)


def test_a_report_links_a_track_of_every_playlist_service():
    from discjockey import report
    assert report.service_link("soundcloud:900000101") == (
        "[SoundCloud](https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900000101) · ")
    assert report.service_link("youtube_music:EXAMPLEid01") == (
        "[YouTube Music](https://music.youtube.com/watch?v=EXAMPLEid01) · ")


def test_the_sections_no_run_makes_any_more_are_gone():
    # moved, adopted and conflicts belonged to the old relocate step: the hub still reads them in stored run
    # results, but no run writes them and a new report has no heading for them
    assert not {"moved", "adopted", "conflicts"} & {key for key, _ in SECTIONS}
    log = RunLog(STARTED)
    log.add(Result("new_lossless", "A", "Artist", "Song", "t1", "q"))
    assert "Moved to another folder" not in render_report(log, FINISHED)
