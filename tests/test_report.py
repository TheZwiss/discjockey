import json
from pathlib import Path
from datetime import datetime

import pytest

from discjockey.events import Result
from discjockey.library import Paths
from discjockey.models import Action, Plan, SourceTrack
from discjockey.report import (
    SECTIONS, RunLog, auto_upgrade_line, check_text, render_line, render_not_lossless, render_plan, render_report,
    summary, upgrades_waiting, write_not_lossless, write_run,
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
    assert keys.index("upgrade_ready") < keys.index("checked")
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


# --- Auto-upgrade in the report (issue 33 stage C; plan stage C §1.5, §3) ---

def block(done=0, rekordbox=0, later=0, refused=0, backup="20261109T030639Z", **extra) -> dict:
    """An Outcome.to_dict() with that many results of each kind: `rekordbox` waits for rekordbox to be closed, `later`
    for the next sync (Stop, another window)."""
    results = ([{"track": f"d{i}", "name": "A – T", "state": "done", "reason": None, "message": "m", "how": "in_place"}
                for i in range(done)]
               + [{"track": f"r{i}", "name": "A – T", "state": "waiting", "reason": "rekordbox_open", "message": "w",
                   "how": "in_place"} for i in range(rekordbox)]
               + [{"track": f"n{i}", "name": "A – T", "state": "waiting", "reason": ["not_reached", "busy"][i % 2],
                   "message": "w", "how": "in_place"} for i in range(later)]
               + [{"track": f"x{i}", "name": "A – T", "state": "refused", "reason": "cloud", "message": "c",
                   "how": "in_place"} for i in range(refused)])
    return {"batch": 3 if done or later or refused else None, "backup": backup, "done": done,
            "waiting": rekordbox + later, "refused": refused, "failed": 0, "stopped": False, "dry_run": False,
            "results": results, **extra}


@pytest.mark.parametrize("args, line", [
    (dict(done=1), "Upgraded 1 track; your cues stayed."),
    (dict(done=12), "Upgraded 12 tracks; your cues stayed."),
    (dict(done=12, rekordbox=3, refused=1),
     "Upgraded 12 tracks; your cues stayed. 3 wait for rekordbox to be closed. 1 couldn't go in; To-do says why."),
    (dict(done=2, rekordbox=1), "Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox to be closed."),
    (dict(done=2, later=1), "Upgraded 2 tracks; your cues stayed. 1 waits for your next sync."),
    (dict(done=2, rekordbox=2, later=3, refused=2),
     "Upgraded 2 tracks; your cues stayed. 2 wait for rekordbox to be closed. 3 wait for your next sync. "
     "2 couldn't go in; To-do says why."),
    (dict(rekordbox=1), "1 upgrade waits for rekordbox to be closed."),
    (dict(rekordbox=4), "4 upgrades wait for rekordbox to be closed."),
    (dict(later=1), "1 upgrade waits for your next sync."),
    (dict(later=2), "2 upgrades wait for your next sync."),
    (dict(refused=1), "1 upgrade couldn't go in; To-do says why."),
    (dict(refused=3), "3 upgrades couldn't go in; To-do says why."),
    (dict(rekordbox=2, later=1, refused=1),
     "2 upgrades wait for rekordbox to be closed. 1 upgrade waits for your next sync. "
     "1 upgrade couldn't go in; To-do says why."),
])
def test_the_summary_line_for_every_case(args, line):
    assert auto_upgrade_line(block(**args)) == line


def test_the_summary_line_is_none_for_no_block_and_for_nothing_to_say():
    assert auto_upgrade_line(None) is None and auto_upgrade_line({}) is None
    assert auto_upgrade_line(block()) is None


def test_the_report_has_the_upgraded_section_the_backup_line_and_the_summary_line_on_top():
    log = RunLog(STARTED)
    log.add(Result("new_lossless", "A", "Artist", "New", "t1", "Qobuz FLAC · verified lossless"))
    log.add(Result("upgraded", "A", "Artist", "Song 0", "t2", "new file Library/A/Artist - Song 0.aiff"))
    log.add(Result("upgraded", "A", "Artist", "Song 1", "t3", "matches exactly"))
    log.add(Result("upgrade_waits", "A", "Artist", "Song 2", "t4", "Waits for rekordbox to be closed."))
    log.auto_upgrade = block(done=2, rekordbox=1)
    text = render_report(log, FINISHED)
    assert "## Upgraded (your cues stayed) (2)" in text and "## Upgrades still waiting (1)" in text
    lines = text.splitlines()
    heading = lines.index("## Upgraded (your cues stayed) (2)")
    assert lines[heading + 2].startswith("- [A] Artist - Song 0") and lines[heading + 3].startswith("- [A] Artist - Song 1")
    assert lines[heading + 4] == "" and lines[heading + 5] == \
        "Backup of your rekordbox library from before these upgrades: 20261109T030639Z"
    top = "Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox to be closed."
    assert top in lines and lines.index(top) < lines.index("## New lossless tracks (1)")
    assert text.index("## Upgraded") < text.index("## Upgrades still waiting")      # after the new-file sections
    assert text.index("## New lossless tracks") < text.index("## Upgraded")


def test_no_backup_line_without_a_backup_or_without_upgraded_tracks():
    log = RunLog(STARTED)
    log.add(Result("upgraded", "A", "Artist", "Song", "t2", "n"))
    log.auto_upgrade = block(done=1, backup=None)
    assert "from before these upgrades" not in render_report(log, FINISHED)
    waiting = RunLog(STARTED)
    waiting.add(Result("upgrade_waits", "A", "Artist", "Song", "t2", "w"))
    waiting.auto_upgrade = block(rekordbox=1)
    assert "from before these upgrades" not in render_report(waiting, FINISHED)


def test_the_json_carries_the_block_only_when_the_phase_ran(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    log = RunLog(STARTED)
    assert "auto_upgrade" not in json.loads(write_run(paths, log, FINISHED, 0).with_suffix(".json").read_text())
    log.auto_upgrade = block(done=1)
    data = json.loads(write_run(paths, log, FINISHED, 0).with_suffix(".json").read_text())
    assert data["auto_upgrade"] == block(done=1)
    assert [s for s, _ in SECTIONS].index("upgraded") == [s for s, _ in SECTIONS].index("added_new") + 1
    assert [s for s, _ in SECTIONS].index("upgrade_waits") == [s for s, _ in SECTIONS].index("upgraded") + 1


def test_the_console_summary_counts_the_new_sections():
    log = RunLog(STARTED)
    log.add(Result("upgraded", "A", "Artist", "Song", "t2", "n"))
    log.add(Result("upgrade_waits", "A", "Artist", "Song", "t3", "w"))
    out = summary(log, Path("/r.md"))
    assert "Upgraded (your cues stayed): 1" in out and "Upgrades still waiting: 1" in out
