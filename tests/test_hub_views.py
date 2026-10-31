import unicodedata
from dataclasses import replace
from datetime import date, datetime

import time

import pytest

from discjockey.hub import views
from discjockey.hub.jobs import PreviewStore
from discjockey.models import (Action, BatchResult, BatchRow, FetchedPlaylist, MoveRow, Plan, PlannedMove, PlaylistInfo,
                               PlaylistLine, PlaylistRecord, RecordedTrack, SourceTrack)
from discjockey.planner import ENTRY_KEYS, TidyRow, tidy_rows
from discjockey import playlists_file as pf
from discjockey.playlists_file import Loaded, Row
from discjockey.tidy import rename_offer
from discjockey.run import Prepared
from discjockey.settings import Account, Settings

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 21, 47)
SETUP_OK = {"complete": True, "playlists": True}


def e(status="lossless", folder="A", cutoff=None, in_playlists=True, **kw):
    entry = dict.fromkeys(ENTRY_KEYS)
    entry.update(aliases=[], artist="Artist", title="Song", duration_ms=180000, folder=folder, status=status,
                 path=None if status == "missing" else f"Library/{folder}/x.aiff", cutoff_hz=cutoff,
                 source=None if status == "missing" else "qobuz", rejected_sources=[], in_playlists=in_playlists)
    entry.update(kw)
    return entry


def state(**tracks):
    return {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}}


def t(tid):
    return SourceTrack(tid, f"Song {tid}", ("Artist",), "Al", None, 180000, None)


def a(kind, tid, reason="", **kw):
    return Action(kind, tid, "A", t(tid), (0, 0), reason=reason, **kw)


def store_with(actions, st=None):
    store = PreviewStore()
    st = st or state()
    store.ready(Prepared(None, st, Settings(), Plan(st, actions, [], []), None), datetime(2026, 10, 20, 21, 45))
    return store


@pytest.mark.parametrize("entry,cls,label", [
    (e(), "lossless", "LOSSLESS"),
    (e("not_lossless", cutoff=20000), "good_lossy", "20.0 kHz"),
    (e("not_lossless", cutoff=17000), "weak", "17.0 kHz"),
    (e("not_lossless", cutoff=16000), "weak", "16.0 kHz"),
    (e("not_lossless", cutoff=None), "good_lossy", "LOSSY"),
    (e("fake_lossless", cutoff=16000), "fake", "FAKE · 16.0 kHz"),
    (e("missing"), "missing", "NOT FOUND"),
])
def test_quality_classes(entry, cls, label):
    assert (views.quality_class(entry), views.quality_label(entry)) == (cls, label)


def test_lossless_share_counts_tracks_in_playlists_hidden_ones_too():
    s = state(a=e(), b=e("not_lossless", cutoff=16000, hidden=True), c=e("missing"), d=e(in_playlists=False),
              f=e())
    share = views.lossless_share(s)
    assert (share["share"], share["lossless"], share["total"]) == (0.5, 2, 4)
    assert share["by_quality"] == {"lossless": 2, "good_lossy": 0, "weak": 1, "fake": 0, "missing": 1}


def test_lossless_share_without_tracks_is_a_dash():
    assert views.lossless_share(state())["share"] is None


@pytest.mark.parametrize("downloads,minutes", [(0, 0), (1, 5), (4, 5), (12, 15), (21, 25), (60, 70)])
def test_run_minutes(downloads, minutes):
    assert views.run_minutes(downloads) == minutes


@pytest.mark.parametrize("rest,remaining,limit,days", [
    (0, 10, 60, 0), (12, 43, 60, 1), (43, 43, 60, 1), (44, 43, 60, 2), (250, 23, 60, 1 + 4),
    (108, 30, 66, 1 + 2),  # some left today: today counts as a day
    (250, 0, 60, 5), (108, 0, 66, 2), (1, 0, 60, 1),  # nothing left today: it starts tomorrow, today isn't a day
])
def test_days_to_load(rest, remaining, limit, days):
    assert views.days_to_load(rest, remaining, limit) == days


def test_still_to_load_with_nothing_left_today_does_not_fit_today():
    store = store_with([a("acquire", f"t{i}", "new") for i in range(108)])
    assert views.still_to_load(store.prep, {"remaining": 0, "limit": 66}, state()) == {
        "count": 108, "days": 2, "fits_today": False}
    one = store_with([a("acquire", "t0", "new")])
    assert views.still_to_load(one.prep, {"remaining": 0, "limit": 66}, state()) == {
        "count": 1, "days": 1, "fits_today": False}


@pytest.mark.parametrize("limit,level,label", [(10, 1, "careful"), (40, 1, "careful"), (41, 2, "normal"),
                                               (60, 2, "normal"), (80, 3, "faster"), (90, 4, "fast"),
                                               (100, 4, "fast"), (101, 5, "risky")])
def test_assessment(limit, level, label):
    assert views.assessment(limit) == {"level": level, "label": label}


def test_budget_numbers_with_carry_over_and_extra():
    s = state()
    s["qobuz_usage"]["days"] = {"2026-10-19": 40, "2026-10-20": 37}
    money = views.budget(s, Settings(60, "2026-10-20", 5), TODAY)
    assert money == {"used": 37, "allowance": 85, "limit": 60, "carry_over": 20, "extra": 5, "remaining": 48}


def test_plan_counts_and_estimate():
    actions = [a("acquire", "t1", "new"), a("acquire", "t2", "retry"), a("adopt_bought", "t4"), a("upgrade", "t5")]
    assert views.plan_counts(actions) == {"new": 1, "retries": 1, "redownloads": 0, "bought": 1,
                                          "weekly_checks": 1}
    assert views.estimate(actions, {"remaining": 2, "limit": 60}) == {
        "duration_min": 5, "qobuz_limit": 60, "qobuz_needed": 3, "qobuz_left": 2, "qobuz_uses": 2,
        "accounts": [], "left": 2, "limit": 60}
    many = [a("acquire", f"n{i}") for i in range(195)]
    assert views.estimate(many, {"remaining": 10, "limit": 60})["duration_min"] == 10  # the rest waits, quickly
    assert views.estimate(many, {"remaining": 0, "limit": 60})["duration_min"] == 0


def test_minutes_table_is_the_formula_once():
    table = views.minutes_by_downloads(200)
    assert len(table) == 201 and table[0] == 0
    assert [table[n] for n in (1, 10, 45, 195)] == [5, 10, 50, 230]  # round(10.5) == 10, round(45.5) == 46
    assert table == [views.run_minutes(n) for n in range(201)]
    assert views.minutes_by_downloads(0) == [0]


def test_sync_preview_gives_the_minutes_for_every_count_the_page_can_tick():
    actions = [a("acquire", f"n{i}", "new") for i in range(12)] + [a("adopt_bought", "m1"), a("upgrade", "u1")]
    st = state()
    p = views.sync_preview(store_with(actions, st), st, Settings(), TODAY, NOW, False)
    est = p["estimate"]
    assert est["qobuz_needed"] == 13
    # one entry for 0 .. the downloads that fit today: the page ticks any subset of them
    assert est["minutes_by_downloads"] == views.minutes_by_downloads(est["qobuz_uses"])
    assert est["duration_min"] == est["minutes_by_downloads"][-1]
    assert "minutes_by_downloads" not in views.estimate(actions, None)  # the dashboard's estimate stays as it was


def test_sync_preview_names_the_folder_of_an_own_song_never_blank():
    # an upgrade check of an imported file belongs to no playlist: its action has no folder (live check, 2026-10-31)
    own = Action("upgrade", "own1", "", t("own1"), (1, 0))
    st = state(own1=e(folder="", path="/Music/Old/Techno/x.mp3"), own2=e(folder="", path=None))
    actions = [a("upgrade", "u1"), own, Action("upgrade", "own2", "", t("own2"), (1, 1))]
    store = store_with(actions, st)
    rows = {r["track_id"]: r for g in views.sync_preview(store, st, Settings(), TODAY, NOW, False,
                                                         where=lambda path: "Techno")["groups"] for r in g["actions"]}
    assert (rows["u1"]["folder"], rows["own1"]["folder"], rows["own2"]["folder"]) == ("A", "Techno", views.OWN_MUSIC)
    bare = views.sync_preview(store, st, Settings(), TODAY, NOW, False)["groups"][0]["actions"]
    assert all(r["folder"] for r in bare)


def test_sync_preview_covers_come_from_the_tracks_own_file_when_the_service_has_none():
    # the live card of the Sync page takes these links for a track whose service gave no picture (a folder track, or
    # one that is not on Spotify): its file's artwork, else nothing (the page draws its placeholder)
    own = Action("upgrade", "own1", "", t("own1"), (1, 0))
    bare = Action("upgrade", "own2", "", t("own2"), (1, 1))
    st = state(own1=e(folder="", path="/Music/Old/Techno/Ko-lab - Song.aiff"), own2=e(folder="", path="/Music/Old/x.aiff"))
    store = store_with([own, bare], st)
    links = {"own1": "cache/covers/own1.jpg"}
    rows = {r["track_id"]: r for g in views.sync_preview(store, st, Settings(), TODAY, NOW, False,
                                                         cover=lambda tid, entry: links.get(tid))["groups"]
            for r in g["actions"]}
    assert rows["own1"]["cover_url"] == "cache/covers/own1.jpg" and rows["own2"]["cover_url"] is None


def test_still_to_load():
    money = {"remaining": 10, "limit": 60}
    store = store_with([a("acquire", f"t{i}", "new") for i in range(12)] + [a("upgrade", "u")])
    assert views.still_to_load(store.prep, money, state()) == {"count": 12, "days": 2, "fits_today": False}
    assert views.still_to_load(None, money, state()) == {"count": None, "days": None, "fits_today": None}
    never = state()
    never["never"] = {"t0": {}, "t1": {}, "t2": {}}
    assert views.still_to_load(store.prep, money, never) == {"count": 9, "days": 1, "fits_today": True}


def test_read_status():
    store = store_with([])
    st = views.read_status(store, NOW, False, [])
    assert st["read_at"] == "2026-10-20T21:45:00" and st["minutes_ago"] == 2 and not st["offline"]
    assert st["problem_service"] is None and st["services"] == []
    store.failed("offline", "Cannot reach Spotify.")
    st = views.read_status(store, NOW, True, [])
    assert st["offline"] and st["problem"] == "offline" and st["reading"] and st["read_at"] == "2026-10-20T21:45:00"
    assert st["problem_service"] is None


def test_read_status_names_the_service_of_a_problem_and_each_login():
    store = store_with([])
    store.failed("not_set_up", "Qobuz isn't set up yet.", "qobuz")
    st = views.read_status(store, NOW, False, [("spotify", True), ("qobuz", False)])
    assert (st["problem"], st["problem_service"]) == ("not_set_up", "qobuz")
    assert st["services"] == [{"service": "spotify", "name": "Spotify", "connected": True},
                              {"service": "qobuz", "name": "Qobuz", "connected": False}]
    store.ready(store.prep, NOW)  # a good read clears the problem, service included
    assert views.read_status(store, NOW, False, [])["problem_service"] is None
    assert views.dashboard(state(), Settings(), store, [], [], SETUP_OK, TODAY, NOW, False,
                           [("qobuz", True)])["read_status"]["services"][0]["connected"] is True
    assert views.sync_preview(store, state(), Settings(), TODAY, NOW, False,
                              logins=[("qobuz", True)])["read_status"]["services"][0]["service"] == "qobuz"


def test_playlist_rows_name_their_service_and_info_carries_the_hint():
    loaded = Loaded([Row("A", "https://open.spotify.com/playlist/0DiscjockeyExampleList"),
                     Row("B", "https://open.qobuz.com/playlist/900000001")], "v", None)
    infos = {"qobuz:900000001": PlaylistInfo("qobuz", "900000001", "Example", "7", "Example Curator", False, None, 3,
                                             False, True)}
    rows = views.playlists(loaded, {}, infos, state())["rows"]
    assert [(r["playlist_id"], r["service"], r["service_name"]) for r in rows] == [
        ("0DiscjockeyExampleList", "spotify", "Spotify"), ("qobuz:900000001", "qobuz", "Qobuz")]
    assert rows[0]["info"] is None
    assert rows[1]["info"]["hint"] == "Make it public in Qobuz, or use one of your own playlists." and rows[1]["tracks"] == 3
    spotify_info = PlaylistInfo("spotify", "x", "N", "o", "O", False, None, 1, False, False)
    assert views.info_dict(spotify_info)["hint"].startswith("Follow ≠ own")


REPORT = {"started": "2026-10-19T21:47:00", "finished": "2026-10-19T22:11:00", "exit_code": 1, "results": [
    {"section": "new_lossless", "folder": "A", "artist": "X", "title": "1", "track_id": "t1", "status": "lossless",
     "path": "Library/A/X - 1.aiff"},
    {"section": "new_not_lossless", "folder": "B", "artist": "X", "title": "2", "track_id": "t2",
     "status": "not_lossless", "path": "Library/B/not_lossless/X - 2.aiff"},
    {"section": "bought", "folder": "A", "artist": "X", "title": "3", "track_id": "t3", "status": "fake_lossless",
     "path": "Library/A/not_lossless/X - 3.wav"},
    {"section": "moved", "folder": "A", "artist": "X", "title": "4", "track_id": "t4"},
    {"section": "missing", "folder": "A", "artist": "X", "title": "5", "track_id": "t5", "error_kind": "not_found"},
    {"section": "errors", "folder": "A", "artist": "X", "title": "6", "track_id": "t6", "error_kind": "network"},
    {"section": "recovered", "folder": "", "artist": "", "title": "", "track_id": None, "note": "Finished ..."},
]}


def test_run_summary():
    s = views.run_summary("2026-10-19_214700", REPORT)
    assert s["duration_s"] == 24 * 60 and s["exit_code"] == 1 and s["stopped_after"] is None
    assert s["counts"] == {"lossless": 1, "lossy": 2, "problems": 2, "moved": 1}


def test_stopped_run_says_after_how_many_tracks():
    data = {**REPORT, "exit_code": 130, "results": REPORT["results"] + [
        {"section": "queued", "track_id": "t7", "note": "stopped before this track was done"},
        {"section": "queued", "track_id": "t8", "note": "left out of this run by you"},
        {"section": "queued", "track_id": "t9", "note": "left out of this run by you"}]}
    assert views.run_summary("x", data)["stopped_after"] == 6  # unticked tracks are not "after N tracks"


def test_runs_newest_first():
    assert [r["run_id"] for r in views.runs([("2026-10-12_100000", REPORT), ("2026-10-19_214700", REPORT)])] == [
        "2026-10-19_214700", "2026-10-12_100000"]


def test_run_detail_for_the_end_screen():
    s = state(u=e("not_lossless", upgrade={"file": "Upgrades ready/A/x.aiff", "alignment": {"result": "exact"}}))
    d = views.run_detail("2026-10-19_214700", REPORT, s)
    assert [r["track_id"] for r in d["needs_you"]] == ["t5", "t6"]
    assert d["for_rekordbox"] == {"new_files": 3, "folders": ["Library/A", "Library/A/not_lossless",
                                                              "Library/B/not_lossless"]}
    assert d["upgrades_ready"] == 1 and d["report_md"] == "reports/2026-10-19_214700.md"
    assert [r["title"] for r in d["sections"]["new_lossless"]] == ["1"]
    assert d["queued"] == 0 and d["folder_order"] == [] and "cover_url" not in d["sections"]["new_lossless"][0]


def test_run_detail_gives_each_row_its_cover_and_the_playlist_order():
    data = {**REPORT, "exit_code": 130, "results": REPORT["results"] + [
        {"section": "queued", "track_id": "t7", "note": "stopped before this track was done"},
        {"section": "queued", "track_id": "t8", "note": "left out of this run by you"}]}
    asked = []

    def cover(track_id, e):
        asked.append(track_id)
        return f"cover/{track_id}" if track_id != "t2" else None
    d = views.run_detail("x", data, state(t1=e()), cover=cover, folder_order=["B", "A"])
    assert d["sections"]["new_lossless"][0]["cover_url"] == "cover/t1"
    assert d["sections"]["new_not_lossless"][0]["cover_url"] is None
    assert d["needs_you"][0]["cover_url"] == "cover/t5"
    assert "t7" not in asked and "t8" not in asked  # the tracks still waiting get no cover (not shown one by one)
    assert d["queued"] == 2 and d["folder_order"] == ["B", "A"]


def test_dashboard():
    s = state(a=e(), b=e("not_lossless", cutoff=16000), c=e("missing"),
              u=e("not_lossless", cutoff=20000, upgrade={"file": "f", "alignment": {"result": "shifted"}}))
    s["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": 37}
    store = store_with([a("acquire", "n1", "new"), a("adopt_bought", "m1"), a("upgrade", "u1")], s)
    d = views.dashboard(s, Settings(), store, [("2026-10-19_214700", REPORT)], ["A"], SETUP_OK, TODAY, NOW, False)
    assert d["greeting"] == "Good evening" and d["empty"] is None
    assert d["tiles"]["lossless"]["share"] == 0.25 and d["tiles"]["qobuz_today"]["used"] == 37
    assert d["tiles"]["still_to_load"] == {"count": 1, "days": 1, "fits_today": True}
    assert d["ready"]["counts"]["new"] == 1 and d["ready"]["duration_min"] == 5 and d["ready"]["actions"] == 3
    assert d["needs_you"] == {"upgrades": 1, "swappable": 1, "not_found": 1, "weak": 1}
    assert d["folders"][0]["folder"] == "A" and d["folders"][0]["tracks"] == 4
    assert d["last_runs"][0]["run_id"] == "2026-10-19_214700" and d["next_checks"] == 1


@pytest.mark.parametrize("setup,tracks,empty", [
    ({"complete": False, "playlists": False}, {}, "no_playlists"),
    ({"complete": False, "playlists": True}, {}, "not_set_up"),
    (SETUP_OK, {}, "empty_library"),
])
def test_dashboard_first_run_states(setup, tracks, empty):
    d = views.dashboard(state(**tracks), Settings(), PreviewStore(), [], [], setup, TODAY, NOW, False)
    assert d["empty"] == empty and d["ready"] is None and d["last_runs"] == []
    assert d["tiles"]["lossless"]["share"] is None and d["tiles"]["still_to_load"]["count"] is None


def test_limits_page_for_qobuz():
    s = state()
    s["qobuz_usage"]["days"] = {"2026-10-07": 12, "2026-10-19": 60, "2026-10-20": 37}
    s["qobuz_usage"]["signals"] = [
        {"time": "2026-09-01T10:00:00", "kind": "login_failed", "message": "old"},
        {"time": "2026-10-19T22:00:00", "kind": "duration_mismatch", "message": "a preview"},
        {"time": "2026-10-20T10:00:00", "kind": "auto_stop", "message": "3 failed"},
    ]
    store = store_with([a("acquire", f"t{i}", "new") for i in range(250)], s)
    q = views.limits("qobuz", s, Settings(60), store.prep, TODAY)["usage"]
    assert q["today"]["used"] == 37 and q["today"]["allowance"] == 60
    assert len(q["days"]) == 14 and q["days"][0] == {"date": "2026-10-07", "used": 12}
    assert q["days"][-1] == {"date": "2026-10-20", "used": 37}
    assert q["still_to_load"] == {"count": 250, "days": 1 + 4, "fits_today": False}
    assert [x["kind"] for x in q["signals"]] == ["duration_mismatch", "auto_stop"]
    assert q["signal_summary"]["auto_stop"] == 1 and q["signal_summary"]["login_failed"] == 0
    assert q["assessment"] == {"level": 2, "label": "normal"} and q["setting"]["recommended"] == 60


def test_limits_what_if_for_qobuz():
    s = state()
    s["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": 37}
    store = store_with([a("acquire", f"t{i}", "new") for i in range(250)], s)
    w = views.limits_what_if("qobuz", 90, 20, s, Settings(60), store.prep, TODAY)
    assert w["assessment"] == {"level": 4, "label": "fast"}
    assert (w["allowance_today"], w["remaining_today"]) == (90 + 30 + 20, 103)  # carry-over follows the limit
    assert w["days_to_load"] == 1 + 2 and w["run_minutes"] == 105


# --- tracks, library, to-do, sync preview, playlists ---

UPGRADE = {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz", "source_id": "q1",
           "source_format": "flac", "found": "2026-10-18",
           "alignment": {"result": "shifted", "offset_samples": -1014, "offset_ms": -23.0, "drift_ms": 0.2,
                         "text": "lines up after shifting by 23 ms"}}


def cover(tid, entry):
    return f"cover:{tid}"


def media(tid, entry):
    return f"media:{entry['path']}"


def test_track_row():
    row = views.track_row("t1", e("not_lossless", cutoff=16000, source="youtube", duration_ms=268000,
                                   upgrade=UPGRADE), cover)
    assert row == {"track_id": "t1", "artist": "Artist", "title": "Song", "folder": "A", "duration_s": 268.0,
                   "status": "not_lossless", "quality": "weak", "quality_label": "16.0 kHz", "cutoff_hz": 16000,
                   "source": "youtube", "source_name": "YouTube", "in_playlists": True, "own": False,
                   "hidden": False, "upgrade_ready": True, "path": "Library/A/x.aiff", "added": None, "cover_url": "cover:t1"}


@pytest.mark.parametrize("alignment,text", [
    ({"result": "exact"}, "matches exactly, cues stay"),
    ({"result": "shifted", "offset_ms": -23.0}, "aligned by 23 ms, cues stay"),
    ({"result": "different"}, "doesn't match: would be a new rekordbox entry"),
    (None, "could not compare the two versions"),
])
def test_cue_text(alignment, text):
    assert views.cue_text(alignment) == text
    assert views.cue_text(alignment, can_swap=True) == text


# a file that can't be swapped (MP3, WAV...) goes in as a new file: a new rekordbox entry, cues only by relocating
NO_SWAP_SAME = "same edit, but a new rekordbox entry: relocate the old one to the new file to keep its cues"


@pytest.mark.parametrize("alignment,can_swap,text", [
    ({"result": "exact"}, True, "matches exactly, cues stay"),
    ({"result": "exact"}, False, NO_SWAP_SAME),
    ({"result": "shifted", "offset_ms": -23.0}, True, "aligned by 23 ms, cues stay"),
    ({"result": "shifted", "offset_ms": -23.0}, False,
     "same edit, 23 ms apart, but a new rekordbox entry: relocate the old one to the new file to keep its cues"),
    ({"result": "different"}, True, "doesn't match: would be a new rekordbox entry"),
    ({"result": "different"}, False, "doesn't match: would be a new rekordbox entry"),
    ({"result": "unknown"}, True, "could not compare the two versions"),
    ({"result": "unknown"}, False, "could not compare the two versions"),
    (None, False, "could not compare the two versions"),
])
def test_cue_text_by_match_and_swap(alignment, can_swap, text):
    assert views.cue_text(alignment, can_swap) == text


@pytest.mark.parametrize("path,result,swap_safe,swap_possible,text", [
    ("Library/A/x.aiff", "exact", True, True, "matches exactly, cues stay"),
    ("Library/A/x.aif", "exact", True, True, "matches exactly, cues stay"),
    ("Library/A/x.mp3", "exact", True, False, NO_SWAP_SAME),
    ("Library/A/x.wav", "exact", True, False, NO_SWAP_SAME),
    ("Library/A/x.mp3", "different", False, False, "doesn't match: would be a new rekordbox entry"),
    ("Library/A/x.aiff", "different", False, True, "doesn't match: would be a new rekordbox entry"),
    ("Library/A/x.mp3", "unknown", False, False, "could not compare the two versions"),
])
def test_the_card_and_the_todo_row_say_what_the_file_can_do(path, result, swap_safe, swap_possible, text):
    """The card line combines the measurement with whether the file can be swapped (AIFF only); the To-do row says
    the same, and the UI offers Swap only when swap_safe and swap_possible (todoModel.actionsFor)."""
    entry = e("not_lossless", path=path, upgrade={**UPGRADE, "alignment": {"result": result, "offset_ms": 0.0}})
    up = views.track_detail("t1", entry, [], TODAY)["upgrade"]
    assert (up["swap_safe"], up["swap_possible"], up["cue_text"]) == (swap_safe, swap_possible, text)
    row = {i["track_id"]: i for g in views.todo(state(t1=entry), "all", False, {}, TODAY)["groups"]
           for i in g["items"]}["t1"]
    assert row["group"] == "upgrade_ready" and row["detail"] == ROW_STATUS[(result, swap_possible)]


# the To-do row's short line (the panel says the rest)
ROW_STATUS = {("exact", True): "Lossless ready · cues can stay", ("exact", False): "Lossless ready · new rekordbox track",
              ("different", False): "Lossless ready · different edit", ("different", True): "Lossless ready · different edit",
              ("unknown", False): "Lossless ready · not compared"}


@pytest.mark.parametrize("up,can_swap,text", [
    ({"alignment": {"result": "shifted"}}, True, "Lossless ready · cues can stay"),
    ({"alignment": {"result": "shifted"}}, False, "Lossless ready · new rekordbox track"),
    ({"alignment": None}, True, "Lossless ready · not compared"),
    ({"status": "not_lossless", "kbps": 256, "alignment": {"result": "exact"}}, False,
     "256 kbps ready · new rekordbox track"),
])
def test_upgrade_status_is_short(up, can_swap, text):
    assert views.upgrade_status(up, can_swap) == text


@pytest.mark.parametrize("up,text", [
    ({"source_format": "flac"}, "FLAC · lossless"),
    ({}, "FLAC · lossless"),
    ({"source_format": "aac", "status": "not_lossless", "kbps": 256}, "AAC · 256 kbps"),
    ({"source_format": "pcm_s16be"}, "PCM · lossless"),
])
def test_upgrade_format_says_the_new_quality(up, text):
    assert views.upgrade_format(up) == text


def test_track_detail():
    entry = e("not_lossless", cutoff=16000, source="youtube", source_id="abcdefghijk", source_format="opus",
              aliases=["t9"], last_upgrade_check="2026-10-17", upgrade=None, path="Library/A/not_lossless/x.aiff")
    fetched = [FetchedPlaylist(PlaylistLine("A", "p1", 1), [t("t1")], []),
               FetchedPlaylist(PlaylistLine("B", "p2", 2), [t("t9")], []),
               FetchedPlaylist(PlaylistLine("C", "p3", 3), [t("other")], [])]
    d = views.track_detail("t1", entry, fetched, TODAY, cover, media)
    assert d["playlists"] == ["A", "B"] and d["in_playlist_count"] == 2
    assert d["quality_line"] == "YouTube OPUS · cutoff 16.0 kHz"
    assert d["source_url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert d["next_qobuz_check"] == "2026-10-24" and d["audio_url"] == "media:Library/A/not_lossless/x.aiff"
    assert d["bought_name"] == "Library/A/Artist - Song.wav"
    assert d["buy_links"]["beatport"] == "https://www.beatport.com/search?q=Artist+Song"
    assert d["upgrade"] is None and "spotify_url" not in d
    assert d["track_link"] == {"url": "https://open.spotify.com/track/t1", "label": "Open in Spotify"}


def test_track_detail_says_why_the_file_is_not_there():
    there = e("lossless", path="/Volumes/Example Drive/x.wav", online=True)
    away = e("lossless", path="/Volumes/Example Drive/x.wav", online=False)
    detail = lambda entry, **kw: views.track_detail("t1", entry, [], TODAY, media=lambda k, en: "media:" + en["path"], **kw)
    assert detail(there)["file_state"] == "here" and detail(there)["audio_url"] == "media:/Volumes/Example Drive/x.wav"
    assert "online" not in detail(there)
    assert detail(away)["file_state"] == "offline" and detail(away)["audio_url"] is None  # the row says it was away
    assert detail(e("lossless", path="Library/A/x.wav"))["file_state"] == "here"  # no key: there
    assert detail(e("missing", online=False))["file_state"] == "here"  # no file, nothing away
    gone = detail(there, exists=False)  # its folder is there, the file is not (since the last scan)
    assert gone["file_state"] == "file_missing" and gone["audio_url"] is None
    assert detail(e("missing"), exists=False)["file_state"] == "here"  # a track without a file has nothing to miss


GATE = {"url": "https://hypeddit.com/a/b", "host": "hypeddit.com", "direct": False, "page": "https://sc/1",
        "title": "Song (Free DL)", "uploader": "Artist"}


def test_track_detail_shows_bitrate_and_the_artists_free_downloads():
    d = views.track_detail("t1", e("not_lossless", cutoff=20100, source="youtube_music", source_format="opus",
                                   source_kbps=135, free_downloads=[GATE]), [], TODAY)
    assert d["quality_line"] == "YouTube Music OPUS 135 kbps · cutoff 20.1 kHz"
    assert d["format_line"] == "Opus · 135 kbps" and d["source_full"] == "YouTube Music"
    assert d["free_downloads"] == [{"url": "https://hypeddit.com/a/b", "host": "hypeddit.com", "direct": False,
                                    "title": "Song (Free DL)", "uploader": "Artist"}]
    assert views.track_detail("t1", e("lossless", free_downloads=[GATE]), [], TODAY)["free_downloads"] == []
    assert views.track_detail("t1", e("missing"), [], TODAY)["free_downloads"] == []  # never looked


def test_format_line():
    assert views.format_line(e("lossless", source="qobuz", source_format="flac")) == "FLAC"
    assert views.format_line(e("lossless", source="manual", source_format="pcm_s16be")) == "uncompressed PCM"
    assert views.format_line(e("not_lossless", source="soundcloud", source_format="aac")) == "AAC"  # not looked up yet
    assert views.format_line(e("fake_lossless", source="qobuz", source_format="flac", source_kbps=900)) == "FLAC"
    assert views.format_line(e("missing")) is None


def test_todo_rows_say_when_a_free_download_exists():
    s = state(t1=e("not_lossless", cutoff=17900, source="soundcloud", free_downloads=[GATE], source_kbps=160),
              t2=e("missing", title="Gone", free_downloads=[GATE]), t3=e("not_lossless", title="Other", cutoff=20000))
    rows = {i["track_id"]: i for g in views.todo(s, "all", False, {}, TODAY)["groups"] for i in g["items"]}
    assert rows["t1"]["free"] and rows["t2"]["free"] and not rows["t3"]["free"]
    assert rows["t1"]["detail"] == "SoundCloud · 160 kbps"  # the kHz is the badge


def test_track_detail_with_a_parked_upgrade():
    d = views.track_detail("t1", e("not_lossless", cutoff=20000, source="youtube_music", source_format="opus",
                                   upgrade=UPGRADE), [], TODAY, cover, media)
    up = d["upgrade"]
    assert up["cue_text"] == "aligned by 23 ms, cues stay" and up["swap_safe"] and up["swap_possible"]
    assert up["quality_line"] == "Qobuz FLAC · verified lossless"
    assert up["audio_url"] == "media:Upgrades ready/A/Artist - Song.aiff"
    assert d["next_qobuz_check"] is None and d["playlists"] is None


def test_wav_files_cannot_be_swapped():
    d = views.track_detail("t1", e("not_lossless", path="Library/A/x.wav", upgrade=UPGRADE), [], TODAY)
    assert d["upgrade"]["swap_safe"] and not d["upgrade"]["swap_possible"]


@pytest.mark.parametrize("entry,when", [
    (e("missing", last_attempt="2026-10-16"), "2026-10-23"),
    (e("missing", last_attempt="2026-10-01"), "next_sync"),
    (e("not_lossless", last_upgrade_check=None), "next_sync"),
    (e("lossless"), None),
    (e("missing", in_playlists=False), None),
])
def test_next_check(entry, when):
    assert views.next_check(entry, TODAY) == when


LIB = state(
    a=e(folder="Hard_Bounce", artist="Vatoz Locoz", title="Gimme Gimme", duration_ms=156000, source="qobuz"),
    b=e("not_lossless", folder="Hard_Bounce", artist="Armin Hermann", title="Get Naughty", cutoff=16000,
        source="youtube", duration_ms=268000, upgrade=UPGRADE),
    c=e("not_lossless", folder="Hard_Bounce", artist="Balling", title="Balling (LÄUFF Remix)", cutoff=20000,
        source="youtube_music", duration_ms=192000),
    d=e(folder="Bouncy", artist="DJ TALLBOY", title="THE WEEKEND"),
    f=e(folder="Hard_Bounce", artist="Someone", title="Old Favourite", in_playlists=False),
    g=e("missing", folder="Hard_Bounce", artist="Some Artist", title="Gone Track"),
)


def test_library_folder_chips_and_sort():
    lib = views.library(LIB, "folder", "Library/Hard_Bounce", "", "all", "title", lines=[])
    assert [r["title"] for r in lib["rows"]] == ["Balling (LÄUFF Remix)", "Get Naughty", "Gimme Gimme", "Old Favourite"]
    assert lib["chips"] == {"all": 4, "lossless": 2, "good_lossy": 1, "weak": 1, "fake": 0, "upgrade_ready": 1}
    assert lib["summary"] == {"tracks": 4, "lossless_share": 0.5, "upgrades_ready": 1, "to_do": 2, "not_lossless": 2,
                              "by_quality": {"lossless": 2, "good_lossy": 1, "weak": 1, "fake": 0, "missing": 0}}
    assert lib["empty"] is None
    assert [r["title"] for r in views.library(LIB, "folder", "Library/Hard_Bounce", "", "weak", "title", lines=[])["rows"]] == ["Get Naughty"]
    assert [r["title"] for r in views.library(LIB, "folder", "Library/Hard_Bounce", "", "all", "-length", lines=[])["rows"]][0] == "Get Naughty"


def test_library_summary_ignores_search_and_filter():
    """The panel's folder overview stays the folder's, whatever the table shows."""
    whole = views.library(LIB, "folder", "Library/Hard_Bounce", "", "all", "artist", lines=[])["summary"]
    assert views.library(LIB, "folder", "Library/Hard_Bounce", "gimme", "weak", "artist", lines=[])["summary"] == whole


def test_library_summary_counts_the_checked_files_that_are_not_lossless():
    s = state(a=e(folder="A"), b=e("not_lossless", folder="A", cutoff=20000), c=e("not_lossless", folder="A", cutoff=16000),
              d=e("fake_lossless", folder="A", cutoff=16000), g=e("missing", folder="A"),
              **{"local:1": own(import_state="identified")})
    summary = views.library(s, "all", None, "", "all", "artist", lines=[])["summary"]
    assert summary["not_lossless"] == 3 and summary["by_quality"]["lossless"] == 1  # the unchecked own file is in neither
    assert views.library(s, "folder", "Library/A", "", "weak", "artist", lines=[])["summary"]["not_lossless"] == 3  # not narrowed by the filter


LINES = [Row("Hard_Bounce", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"),
         Row("Powertrance", "https://open.qobuz.com/playlist/900000001"),
         Row("Off_Set", "https://open.qobuz.com/playlist/900000002", enabled=False)]


def test_library_subtitle_per_view():
    records = {LINES[0].ref: record("a", "b", "c", "f"), LINES[2].ref: record("a", service="qobuz")}

    def sub(view, key=None, st=LIB, lines=LINES, query=""):
        return views.library(st, view, key, query, "all", "artist", lines=lines, records=records)["subtitle"]
    assert sub("all") == ["5 tracks", "every folder"]
    assert sub("unlisted") == ["1 track", "in no playlist"]
    assert sub("playlist", "Hard_Bounce") == ["4 tracks", "Spotify playlist", "Library › Hard_Bounce"]
    assert sub("playlist", "hard_bounce")[-1] == "Library › Hard_Bounce"  # the line's spelling, not the route's
    assert sub("playlist", "Off_Set") == ["1 track", "Qobuz playlist", "switched off", "Library › Off_Set"]
    assert sub("playlist", "Powertrance") == ["Qobuz playlist", "not read yet"]  # no record of it
    assert sub("playlist", "Hard_Bounce", query="gimme")[0] == "4 tracks"  # the search never changes the count
    assert sub("playlist", "Nowhere") == [] and sub("folder", "Library/Nowhere") == []
    assert sub("folder", "Library/Bouncy") == ["1 track", "no playlist uses it", "Library › Bouncy"]
    assert sub("folder", "Library/Hard_Bounce") == ["4 tracks", "Library › Hard_Bounce"]  # a playlist uses it
    assert sub("folder", "Library/Hard_Bounce", lines=[])[1:] == ["no playlist uses it", "Library › Hard_Bounce"]


def test_library_to_do_counts_only_what_the_to_do_list_shows():
    s = state(**{**LIB["tracks"], "h": e("not_lossless", folder="Hard_Bounce", cutoff=16000, hidden=True)})
    # b (upgrade) and c (good lossy) are to-dos; a is lossless, f is in no playlist, h is hidden
    assert views.library(s, "folder", "Library/Hard_Bounce", "", "all", "artist", lines=[])["summary"]["to_do"] == 2


def test_library_sorts_by_folder_with_unlisted_tracks_last():
    rows = views.library(LIB, "all", None, "", "all", "folder", lines=[])["rows"]
    assert [r["folder"] for r in rows] == ["Bouncy", "Hard_Bounce", "Hard_Bounce", "Hard_Bounce", "Hard_Bounce"]
    assert rows[-1]["track_id"] == "f"


def test_library_search_all_tracks_and_not_in_a_playlist():
    assert [r["track_id"] for r in views.library(LIB, "all", None, "läuff", "all", "artist", lines=[])["rows"]] == ["c"]
    assert views.library(LIB, "all", None, "", "all", "artist", lines=[])["summary"]["tracks"] == 5  # not found ones have no file
    nip = views.library(LIB, "unlisted", None, "", "all", "artist", lines=[])
    assert nip["title"] == "Not in a playlist" and [r["track_id"] for r in nip["rows"]] == ["f"]
    assert views.library(LIB, "all", None, "nothing like this", "all", "artist", lines=[])["empty"] == "no_match"
    assert views.library(state(), "all", None, "", "all", "artist", lines=[])["empty"] == "empty_library"


def test_sidebar():
    lines = [Row("Hard_Bounce", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"),
             Row("Powertrance", "https://open.qobuz.com/playlist/900000001", enabled=False)]
    sb = views.sidebar(LIB, lines, 3)
    assert sb == {"todo": 3, "all_tracks": 5, "not_in_playlist": 1, "limits_warning": False, "favourites": [],
                  "playlists": [{"name": "Hard_Bounce", "ref": "37i9dQZF1DX0XUsuxWHRQd", "service": "spotify",
                                 "enabled": True, "songs": None},
                                {"name": "Powertrance", "ref": "qobuz:900000001", "service": "qobuz",
                                 "enabled": False, "songs": None}],
                  "watched": [], "library_folders": [{"path": "Library/Bouncy", "name": "Bouncy", "files": 1}]}


def test_sidebar_matches_folders_by_folded_name_and_sorts_the_unused_ones():
    st = state(a=e(folder="Zeta"), b=e(folder="alpha"), c=e(folder="Hard_bounce"), d=e("missing", folder="Gone"))
    sb = views.sidebar(st, [Row("Hard_Bounce", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd")], 0)
    assert sb["library_folders"] == [{"path": "Library/alpha", "name": "alpha", "files": 1},
                                     {"path": "Library/Zeta", "name": "Zeta", "files": 1}]  # the disk ignores case
    assert [f["name"] for f in views.sidebar(st, [], 0)["library_folders"]] == ["alpha", "Hard_bounce", "Zeta"]
    assert views.sidebar(st, [], 0)["playlists"] == []


def test_todo_groups_in_order_with_details():
    s = state(**{**LIB["tracks"],
                 "h": e("not_lossless", cutoff=16100, source="soundcloud", artist="Felix Krull", title="Rave Tag",
                        hidden=True),
                 "k": e("fake_lossless", cutoff=16000, artist="Bootleg Crew", title="Party Edit"),
                 "m": e(artist="DJ", title="THE WEEKEND 2"),
                 "n": e("missing", artist="Z", title="Due", last_attempt="2026-10-01")})
    s["tracks"]["g"]["last_attempt"] = "2026-10-16"
    out = views.todo(s, "all", False, {"m": "MOVE BLOCKED · a file is in the way"}, TODAY, cover)
    assert [g["key"] for g in out["groups"]] == ["upgrade_ready", "not_found", "good_lossy", "fake", "other"]
    by = {i["track_id"]: i for g in out["groups"] for i in g["items"]}
    assert by["b"]["detail"] == "Lossless ready · cues can stay" and by["b"]["group"] == "upgrade_ready"
    assert by["g"]["detail"] == "next try in 3 days" and by["n"]["detail"] == "tried again at the next sync"
    assert by["c"]["detail"] == "YT Music" and by["k"]["detail"] == "Qobuz"
    assert by["m"]["detail"] == "MOVE BLOCKED · a file is in the way"
    assert "h" not in by and "f" not in by and out["hidden_count"] == 1
    assert out["chips"] == {"all": 6, "rekordbox_check": 0, "same_song": 0, "duplicate": 0, "upgrade_ready": 1,
                            "not_found": 2, "weak": 0, "good_lossy": 1, "fake": 1, "other": 1}
    shown = views.todo(s, "weak", True, {}, TODAY)
    assert [g["key"] for g in shown["groups"]] == ["weak"] and shown["groups"][0]["items"][0]["track_id"] == "h"
    assert shown["groups"][0]["items"][0]["hidden"] is True


def test_todo_empty_states():
    assert views.todo(state(a=e()), "all", False, {}, TODAY)["empty"] == "all_lossless"
    assert views.todo(state(a=e("missing", hidden=True)), "all", False, {}, TODAY)["empty"] == "all_hidden"
    assert views.todo(state(a=e("missing")), "fake", False, {}, TODAY)["empty"] == "nothing_here"


def test_todo_others_from_the_last_run_and_the_preview():
    report = {"results": [{"section": "conflicts", "track_id": "m"}, {"section": "moved", "track_id": "x"}]}
    st = state()
    store = PreviewStore()
    store.ready(Prepared(None, st, Settings(), Plan(st, [], [("amb", t("amb"), "A", ["Library/A/x.aiff"])], []), None),
                NOW)
    assert views.todo_others(store.prep, report) == {
        "m": "MOVE BLOCKED · a file is in the way", "amb": "SEVERAL FILES · could be this track, nothing done"}
    assert views.todo_others(None, None) == {}


def test_sync_preview_groups_with_keys():
    st = state(m1=e(folder="Bouncy", artist="DJ TALLBOY", title="THE WEEKEND"))
    bought = Action("adopt_bought", "m1", "Hard_Bounce", t("m1"), (0, 0),
                    src="Library/Hard_Bounce/DJ TALLBOY - THE WEEKEND.wav")
    store = PreviewStore()
    plan = Plan(st, [a("acquire", "n1", "new"), a("acquire", "n2", "new"), bought], [], ["m9"], ["a note"])
    st["tracks"]["m9"] = e(artist="Gone", title="Dropped", in_playlists=False)
    store.ready(Prepared(None, st, Settings(), plan, None), datetime(2026, 10, 20, 21, 45))
    p = views.sync_preview(store, st, Settings(), TODAY, NOW, False, cover)
    assert [g["key"] for g in p["groups"]] == ["acquire:new", "adopt_bought"]
    row = p["groups"][1]["actions"][0]
    assert row["key"] == ["adopt_bought", "m1", "Library/Hard_Bounce"] and "from_folder" not in row
    assert (row["artist"], row["to_not_lossless"], row["cover_url"]) == ("DJ TALLBOY", False, "cover:m1")
    new_row = p["groups"][0]["actions"][0]
    assert new_row["key"] == ["acquire", "n1", "Library/A"] and new_row["artist"] == "Artist"
    assert p["estimate"]["qobuz_needed"] == 2 and p["counts"]["bought"] == 1
    assert p["dropped"] == [{"track_id": "m9", "artist": "Gone", "title": "Dropped", "folder": "A"}]
    assert p["notes"] == ["a note"] and p["empty"] is None and p["read_status"]["minutes_ago"] == 2


def test_sync_preview_never_download_moves_at_once():
    st = state(m=e("missing"))
    st["never"] = {"n2": {"artist": "Artist", "title": "x", "folder": "A", "at": "2026-10-18"}}
    store = PreviewStore()
    plan = Plan(st, [a("acquire", "n1", "new"), a("acquire", "n2", "new")], [], [],
                never=[a("acquire", "n3", "new")])  # n3 was marked before the read, then marked back
    store.ready(Prepared(None, st, Settings(), plan, None), datetime(2026, 10, 20, 21, 45))
    p = views.sync_preview(store, st, Settings(), TODAY, NOW, False)
    assert [r["track_id"] for r in p["groups"][0]["actions"]] == ["n1", "n3"]
    assert [r["track_id"] for r in p["never"]] == ["n2"] and p["counts"]["new"] == 2
    assert [r["run"] for r in p["groups"][0]["actions"]] == [0, 1]
    st["never"]["n1"] = st["never"]["n3"] = {}
    p = views.sync_preview(store, st, Settings(), TODAY, NOW, False)
    assert p["groups"] == [] and p["empty"] == "up_to_date" and len(p["never"]) == 3


def test_never_download_is_not_a_to_do():
    st = state(m=e("missing"), k=e("missing"))
    st["never"] = {"m": {}}
    assert [i["track_id"] for g in views.todo(st, "all", False, {}, TODAY)["groups"] for i in g["items"]] == ["k"]
    assert views.needs_you(st)["not_found"] == 1


def test_sync_preview_without_a_read_yet_and_up_to_date():
    assert views.sync_preview(PreviewStore(), state(), Settings(), TODAY, NOW, True)["empty"] == "no_preview"
    assert views.sync_preview(store_with([]), state(), Settings(), TODAY, NOW, False)["empty"] == "up_to_date"


ID1, ID2 = "0DiscjockeyExampleList", "3DiscjockeyExampleList"
OLD = [Row("Hard_Bounce", f"spotify:playlist:{ID1}"), Row("Powertrance", f"spotify:playlist:{ID2}")]
PL_STATE = state(a=e(folder="Hard_Bounce", title="A", path="Library/Hard_Bounce/a.aiff", file_id=1, placed_by="app"),
                 b=e(folder="Hard_Bounce", title="B", path="Library/Hard_Bounce/b.aiff", file_id=2, placed_by="app"),
                 c=e("not_lossless", folder="Hard_Bounce", title="C", cutoff=20000,
                     path="Library/Hard_Bounce/not_lossless/c.aiff", file_id=3, placed_by="app"),
                 d=e(folder="Powertrance", title="D", path="Library/Powertrance/d.aiff", file_id=4, placed_by="app"))
PL_FILES = [x["path"] for x in PL_STATE["tracks"].values()]
PL_STATE["files"] = PL_FILES
PL_TRACKS = {ID1: [t("a"), t("b"), t("c")], ID2: [t("b"), t("c"), t("d"), t("new1")]}
MONEY = {"remaining": 10, "limit": 60}


DIRS = {"Hard_Bounce", "Powertrance"}


def call_change(old, new, tracks, st, files, today, money, cover=None, **kw):
    """views.playlist_change as the api calls it: the maps from the rows, the real offer, the folders of the Library."""
    kw.setdefault("library_dirs", DIRS)
    kw.setdefault("rename_offer", rename_offer)
    kw.setdefault("placement", pf.placement(new, tracks, st))
    kw.setdefault("retargeted", pf.retargeted(old, new, tracks, st))
    return views.playlist_change(old, new, tracks, st, files, today, money, cover, **kw)


def change(new, tracks=PL_TRACKS, **kw):
    return call_change(OLD, new, tracks, PL_STATE, PL_FILES, TODAY, MONEY, **kw)


def test_playlists_page():
    from discjockey.models import PlaylistInfo
    info = PlaylistInfo("spotify", ID1, "Hard Bounce 2026", "dj1", "DJ One", False, "big", 3, True, True)
    page = views.playlists(Loaded(OLD, "v1", None), PL_TRACKS, {ID1: info}, PL_STATE)
    assert page["version"] == "v1" and page["empty"] is None
    first, second = page["rows"]
    assert first["info"]["name"] == "Hard Bounce 2026" and first["info"]["readable"] and first["tracks"] == 3
    assert second["info"] is None and second["quality"] == {"lossless": 2, "good_lossy": 1, "weak": 0, "fake": 0,
                                                            "missing": 1}
    assert [o["track_id"] for o in page["overlaps"]] == ["b", "c"] and page["overlaps"][0]["lands_in"] == "Hard_Bounce"
    assert views.playlists(Loaded([], "", None), {}, {}, state())["empty"] == "no_playlists"
    assert page["tidy"] == {"waiting": 0}
    moved = {**PL_STATE, "tracks": {**PL_STATE["tracks"], "a": {**PL_STATE["tracks"]["a"], "folder": "Powertrance"},
                                    "b": {**PL_STATE["tracks"]["b"], "folder": "Powertrance", "placed_by": "user"}}}
    assert views.playlists(Loaded(OLD, "v1", None), PL_TRACKS, {}, moved)["tidy"] == {"waiting": 1}  # yours: not counted


def test_playlists_overlaps_have_covers_and_say_whether_a_track_has_a_file():
    spotify_only = SourceTrack("n1", "Fresh", ("Newcomer",), "Al", "https://i.scdn.co/image/n1", 180000, None)
    tracks = {ID1: [t("a"), t("b"), spotify_only], ID2: [t("b"), spotify_only]}
    page = views.playlists(Loaded(OLD, "v1", None), tracks, {}, PL_STATE, lambda k, e: f"cover:{k}" if e else None)
    b, n1 = page["overlaps"]
    assert (b["artist"], b["title"], b["cover_url"], b["downloaded"], b["quality"]) == (
        "Artist", "B", "cover:b", True, "lossless")
    assert (n1["artist"], n1["title"], n1["cover_url"], n1["downloaded"], n1["quality"], n1["quality_label"]) == (
        "Newcomer", "Fresh", "https://i.scdn.co/image/n1", False, "missing", None)
    assert n1["folders"] == ["Hard_Bounce", "Powertrance"] and n1["lands_in"] == "Hard_Bounce"


def test_change_reorder():
    c = change([OLD[1], OLD[0]])
    assert c["kind"] == "moves" and c["headline"] == "2 files would sit in a different folder"
    assert c["tidy"]["headline"] == c["headline"] and c["renames"] == []
    assert c["folders"] == [{"folder": "Powertrance", "before": 2, "after": 4},
                            {"folder": "Hard_Bounce", "before": 3, "after": 1}]
    assert "moves" not in c
    assert [(m["track_id"], m["file_id"], m["from"], m["to"], m["from_path"], m["ticked"], m["by_rename"])
            for m in c["tidy"]["rows"]] == [
        ("b", 2, "Hard_Bounce", "Powertrance", "Library/Hard_Bounce/b.aiff", True, None),
        ("c", 3, "Hard_Bounce/not_lossless", "Powertrance/not_lossless", "Library/Hard_Bounce/not_lossless/c.aiff",
         True, None)]
    assert c["checklist"] == ["No downloads, no Qobuz quota used", "Nothing is deleted",
                              "Files move only if you choose to", "Moves can be undone on this page"]


def test_change_rename():
    c = change([Row("Hard Bounce", OLD[0].link), OLD[1]])
    assert (c["kind"], c["headline"]) == ("rename", "3 files would sit in a different folder")
    assert c["renames"] == [{"from": "Hard_Bounce", "to": "Hard Bounce", "files": 3, "offered": True,
                             "why_not": None, "option": "Rename the folder on disk too",
                             "detail": "One folder move instead of 3 file moves."}]
    assert [(r["track_id"], r["by_rename"], r["to"]) for r in c["tidy"]["rows"]] == [
        ("a", "Hard_Bounce", "Hard Bounce"), ("b", "Hard_Bounce", "Hard Bounce"),
        ("c", "Hard_Bounce", "Hard Bounce/not_lossless")]


def test_change_rename_is_not_offered_when_the_new_folder_exists_or_the_old_one_is_still_used():
    taken = call_change(OLD, [Row("Powertrance", OLD[0].link), OLD[1]], PL_TRACKS, PL_STATE, PL_FILES, TODAY,
                                  MONEY)
    assert [(r["offered"], r["why_not"]) for r in taken["renames"]] == [
        (False, "A folder called Powertrance is already in your Library.")]
    assert [r["by_rename"] for r in taken["tidy"]["rows"]] == ["Hard_Bounce"] * len(taken["tidy"]["rows"])
    other = Row("Hard_Bounce", "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")  # another playlist takes the old name
    used = call_change(OLD, [Row("Hard Bounce", OLD[0].link), OLD[1], other], PL_TRACKS,
                                 PL_STATE, PL_FILES, TODAY, MONEY)
    assert [(r["offered"], r["why_not"]) for r in used["renames"]] == [
        (False, "Hard_Bounce is still the folder of another playlist.")]
    assert call_change(OLD, [Row("Hard Bounce", OLD[0].link), OLD[1]], PL_TRACKS, PL_STATE, PL_FILES, TODAY,
                                 MONEY, library_dirs={"Powertrance"})["renames"] == []  # no_folder


def test_change_by_rename_only_when_the_rename_lands_the_file_on_its_target():
    # b and c move to Powertrance for another reason: renaming Hard_Bounce does not put them there
    c = change([OLD[1], Row("Hard Bounce", OLD[0].link)])
    assert {r["track_id"]: r["by_rename"] for r in c["tidy"]["rows"]} == {"a": "Hard_Bounce", "b": None, "c": None}


def test_by_rename_compares_folder_names_by_fold():
    row = TidyRow("a", 1, "Library/hard_bounce/a.aiff", "Library/Hard_New/a.aiff", "app", None)
    assert views._by_rename(row, [("Hard_Bounce", "Hard_New")]) == "Hard_Bounce"
    assert views._by_rename(row, [("Hard_Bounce", "Other")]) is None


def test_change_takes_the_api_maps_when_given():
    c = change([OLD[1], OLD[0]], placement={"b": "Powertrance", "c": "Powertrance"}, retargeted={"c": "Powertrance"})
    assert [r["track_id"] for r in c["tidy"]["rows"]] == ["c"]
    assert c["tidy"]["headline"] == "1 file would sit in a different folder"


def test_change_ticks_follow_placed_by_and_a_name_in_the_way_is_a_skip():
    st = {**PL_STATE, "tracks": {**PL_STATE["tracks"], "b": {**PL_STATE["tracks"]["b"], "placed_by": "user"}},
          "files": PL_FILES + ["Library/Powertrance/not_lossless/c.aiff"]}
    c = call_change(OLD, [OLD[1], OLD[0]], PL_TRACKS, st, st["files"], TODAY, MONEY)
    by = {r["track_id"]: r for r in c["tidy"]["rows"]}
    assert (by["b"]["ticked"], by["b"]["yours"], by["b"]["skip"]) == (False, True, None)
    assert (by["c"]["ticked"], by["c"]["skip"]) == (False, {
        "reason": "name_taken", "text": "A file with this name is already in Powertrance/not_lossless"})


def test_change_add():
    ID3 = "37i9dQZF1DXcBWIGoYBM5M"
    tracks = {**PL_TRACKS, ID3: [t("a"), t("x1"), t("x2")]}
    c = change(OLD + [Row("New", f"spotify:playlist:{ID3}")], tracks)
    assert c["kind"] == "add" and c["headline"] == "2 new downloads, about 1 day at the current limit"
    assert c["checklist"] == ["2 downloads, counted toward your Qobuz limit", "Nothing is deleted",
                              "Happens at the next sync, not right away"]
    assert change(OLD + [Row("New", f"spotify:playlist:{ID3}")])["kind"] == "unknown"


def test_change_switch_off_and_nothing():
    c = change([OLD[0], Row("Powertrance", OLD[1].link, False)])
    assert (c["kind"], c["headline"], c["stopped"]) == ("switch_off", "Files stay, no more updates", 1)
    assert c["tidy"] is None and c["renames"] == [] and c["checklist"][-1] == "Happens at the next sync, not right away"
    assert change(list(OLD))["kind"] == "none"


def test_todo_check_in_rekordbox_group_also_for_lossless_and_hidden_tracks():
    s = state(a=e(rekordbox_check={"reason": "wrong_song", "since": "2026-10-16"}),
              h=e("missing", hidden=True, rekordbox_check={"reason": "added_as_new", "since": "2026-10-16"}))
    out = views.todo(s, "all", False, {}, TODAY)
    assert [g["key"] for g in out["groups"]] == ["rekordbox_check"]
    group = out["groups"][0]
    assert group["label"] == "Check in rekordbox"
    by = {i["track_id"]: i for i in group["items"]}
    assert by["a"]["detail"] == "now the right song: analyse again"
    assert by["a"]["check"]["text"] == ("This track now plays the right song. In rekordbox: analyse it again and delete "
                                        "the old cues (they belong to the wrong song).")
    assert by["h"]["detail"] == "analyse, set the cues again"
    assert by["h"]["check"] == {"reason": "added_as_new", "since": "2026-10-16", "match": None, "offset_ms": None,
                                "moved": False, "old_path": None,
                                "text": "This is a different edit. In rekordbox: analyse it again and set the cues again."}
    assert out["chips"]["rekordbox_check"] == 2 and out["chips"]["all"] == 2 and out["hidden_count"] == 1
    both = views.todo(s, "all", True, {}, TODAY)
    assert [g["key"] for g in both["groups"]] == ["rekordbox_check", "not_found"] and both["chips"]["all"] == 2


def test_todo_check_in_rekordbox_words_an_added_file_by_what_was_measured():
    s = state(a=e(rekordbox_check={"reason": "added_as_new", "since": "2026-10-16", "match": "exact"}),
              b=e(title="B", rekordbox_check={"reason": "added_as_new", "since": "2026-10-16", "match": "different"}))
    by = {i["track_id"]: i for i in views.todo(s, "all", False, {}, TODAY)["groups"][0]["items"]}
    assert by["a"]["detail"] == "relocate, analyse again" and by["a"]["check"]["match"] == "exact"
    assert by["a"]["check"]["text"] == "This is the same edit. In rekordbox: relocate the old entry to the new file, its cues fit."
    assert by["b"]["detail"] == "analyse, set the cues again"
    assert by["b"]["check"]["text"] == "This is a different edit. In rekordbox: analyse it again and set the cues again."


@pytest.mark.parametrize("check,text", [
    ({"reason": "swapped"}, "Reload Tag, analyse again"),
    ({"reason": "swapped", "moved": True}, "relocate, Reload Tag, analyse again"),
    ({"reason": "added_as_new", "match": "shifted"}, "relocate, analyse again"),
    ({"reason": "added_as_new", "match": "unknown"}, "analyse, set the cues again"),
    ({"reason": "wrong_song"}, "now the right song: analyse again"),
    (None, "check it in rekordbox"),
])
def test_check_status_is_short(check, text):
    assert views.check_status(check) == text


def test_check_view_says_where_the_old_file_is_from_the_undo_record():
    c = {"reason": "swapped", "since": "2026-10-31", "match": "shifted", "offset_ms": 12.0, "moved": False,
         "undo": {"kind": "swap", "file": "Library/A/x.aiff", "old": "Superseded/A/x (lossy).aiff"}}
    v = views.check_view(c)
    assert v["old_path"] == "Superseded/A/x (lossy).aiff" and v["match"] == "shifted" and v["offset_ms"] == 12.0
    assert "undo" not in v and v["text"].startswith("The lossless audio is in your file")


def test_change_of_tracks_without_a_file_says_where_they_will_go():
    tracks = {ID1: [t("a"), t("n1"), t("n2")], ID2: [t("n1"), t("n2"), t("d")]}
    c = change([OLD[1], OLD[0]], tracks)
    assert (c["kind"], c["headline"]) == ("reroute", "2 tracks will go to Powertrance instead of Hard_Bounce")
    assert c["tidy"] is None and [(r["track_id"], r["from"], r["to"], r["downloaded"]) for r in c["reroutes"]] == [
        ("n1", "Hard_Bounce", "Powertrance", False), ("n2", "Hard_Bounce", "Powertrance", False)]
    assert c["folders"] == [{"folder": "Powertrance", "before": 1, "after": 3},
                            {"folder": "Hard_Bounce", "before": 3, "after": 1}]
    one = change([OLD[1], OLD[0]], {ID1: [t("a"), t("n1")], ID2: [t("n1"), t("d")]})
    assert one["headline"] == "1 track will go to Powertrance instead of Hard_Bounce"
    renamed = call_change([Row("Fresh", OLD[1].link)], [Row("Fresh 2026", OLD[1].link)],
                                    {ID2: [t("n1")]}, PL_STATE, PL_FILES, TODAY, MONEY)
    assert (renamed["kind"], renamed["headline"]) == ("rename", "1 track will go to the new folder name")


def test_change_headline_for_one_track():
    c = change([OLD[1], OLD[0]], {ID1: [t("a"), t("b"), t("c")], ID2: [t("c"), t("d")]})
    assert c["kind"] == "moves" and c["headline"] == "1 file would sit in a different folder"


def test_limits_tell_the_time_of_the_last_download():
    s = state()
    assert views.limits("qobuz", s, Settings(60), None, TODAY)["usage"]["last_download"] is None
    s["qobuz_usage"]["last_download"] = "2026-10-20T21:47:03"
    assert views.limits("qobuz", s, Settings(60), None, TODAY)["usage"]["last_download"] == "2026-10-20T21:47:03"


def test_rename_headline_for_one_file():
    c = change([Row("Hard Bounce", OLD[0].link), OLD[1]], {ID1: [t("a")], ID2: [t("c"), t("d")]})
    assert (c["kind"], c["headline"]) == ("rename", "1 file would sit in a different folder")


YT = Settings(accounts={"youtube": Account("chrome", 30)})
BOTH = Settings(accounts={"youtube": Account("chrome", 30), "soundcloud": Account("firefox", 60)})


def test_services_of():
    assert views.services_of(Settings()) == ["qobuz"]
    assert views.services_of(BOTH) == ["qobuz", "youtube", "soundcloud"]
    assert views.services_of(Settings(qobuz_skipped=True, accounts=YT.accounts)) == ["youtube"]


def test_qobuz_only_estimate_is_unchanged():
    s = state()
    s["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": 50}
    m = views.moneys(s, Settings(), TODAY)
    assert views.gate(m) == {"remaining": 10, "limit": 60}
    e = views.estimate([a("acquire", f"n{i}") for i in range(12)], views.gate(m), views.split(12, m))
    assert (e["qobuz_left"], e["qobuz_uses"], e["left"], e["limit"]) == (10, 10, 10, 60)
    assert e["accounts"] == [{"service": "qobuz", "name": "Qobuz", "uses": 10, "left": 10, "limit": 60,
                              "about": False}]


def test_with_qobuz_the_accounts_only_catch_what_qobuz_lacks():
    s = state()
    s["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": 50}
    m = views.moneys(s, BOTH, TODAY)
    assert views.gate(m) == {"remaining": 10, "limit": 60}
    youtube = views.split(12, m)[1]
    assert youtube == {"service": "youtube", "name": "YouTube Premium", "uses": None, "left": 40, "limit": 30,
                       "about": True}  # 30 + 10 carried over from a quiet yesterday


def test_without_qobuz_the_accounts_fill_up_in_order():
    s = state()
    s["youtube_usage"] = {"days": {"2026-10-19": 30, "2026-10-20": 26}, "signals": []}
    settings = Settings(qobuz_skipped=True, accounts=BOTH.accounts)
    m = views.moneys(s, settings, TODAY)
    assert views.gate(m) == {"remaining": 4 + 80, "limit": 90}
    assert [(x["service"], x["uses"], x["about"]) for x in views.split(10, m)] == [("youtube", 4, True),
                                                                                    ("soundcloud", 6, True)]


def test_the_estimate_table_agrees_with_split_for_every_count():
    qobuz_low = state()
    qobuz_low["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": 50}
    yt_low = state()
    yt_low["youtube_usage"] = {"days": {"2026-10-19": 30, "2026-10-20": 26}, "signals": []}
    cases = [(qobuz_low, Settings()), (qobuz_low, BOTH),  # Qobuz first, the accounts behind it
             (yt_low, Settings(qobuz_skipped=True, accounts=BOTH.accounts)),  # the accounts fill up in order
             (state(), Settings(qobuz_skipped=True))]  # no limit at all
    for st, settings in cases:
        m = views.moneys(st, settings, TODAY)
        for needed in (0, 3, 12, 120):
            est = views.sync_estimate([a("acquire", f"n{i}") for i in range(needed)], m)
            most = est["qobuz_uses"]
            for count in range(most + 1):  # every subset the page can tick
                for row, want in zip(est["accounts"], views.split(count, m)):
                    table = row["uses_by_downloads"]
                    assert (table is None) == (want["uses"] is None)
                    assert table is None or len(table) == most + 1
                    assert (None if table is None else table[count]) == want["uses"], (row["service"], count)
            for row, whole in zip(est["accounts"], views.split(needed, m)):  # the whole plan is the last entry
                assert row["uses"] == whole["uses"]
                assert row["uses_by_downloads"] is None or row["uses_by_downloads"][-1] == row["uses"]


def test_no_limit_without_any_account():
    m = views.moneys(state(), Settings(qobuz_skipped=True), TODAY)
    assert m == {} and views.gate(m) is None
    e = views.estimate([a("acquire", f"n{i}") for i in range(5)], None)
    assert (e["left"], e["qobuz_uses"], e["duration_min"]) == (None, 5, 5)
    store = store_with([a("acquire", f"t{i}", "new") for i in range(12)])
    assert views.still_to_load(store.prep, None, state()) == {"count": 12, "days": 1, "fits_today": True}


def test_limit_cards():
    s = state()
    s["youtube_usage"] = {"days": {"2026-10-19": 30, "2026-10-20": 3}, "signals": [
        {"time": "2026-10-20T10:00:00", "kind": "bot_check", "message": "x"},
        {"time": "2026-10-20T10:01:00", "kind": "auto_stop", "message": "y"}]}
    cards = views.limit_cards(s, YT, TODAY)
    assert [c["service"] for c in cards] == ["qobuz", "youtube", "soundcloud"]
    assert cards[1] == {"service": "youtube", "name": "YouTube Premium", "set_up": True, "used": 3, "allowance": 30,
                        "warnings": 2, "new_warnings": 2, "paused": True}
    assert cards[2]["set_up"] is False


def test_limits_for_youtube_use_its_own_zones_signals_and_numbers():
    s = state()
    s["youtube_usage"] = {"days": {"2026-10-19": 30, "2026-10-20": 3}, "signals": [
        {"time": "2026-10-20T10:00:00", "kind": "premium_missing", "message": "x"}]}
    store = store_with([a("acquire", f"t{i}", "new") for i in range(12)], s)
    u = views.limits("youtube", s, YT, store.prep, TODAY)["usage"]
    assert (u["service"], u["name"], u["behind"]) == ("youtube", "YouTube Premium", "Qobuz")
    assert u["setting"]["recommended"] == 30 and u["setting"]["zones"][1] == {"name": "normal", "from": 21, "to": 30}
    assert u["signal_summary"] == {"cookies_unreadable": 0, "bot_check": 0, "rate_limited": 0, "refused": 0,
                                   "premium_missing": 1, "download_rejected": 0, "auto_stop": 0}
    assert views.limits("soundcloud", s, YT, store.prep, TODAY)["usage"] is None


def test_limits_what_if_for_an_account():
    s = state()
    s["youtube_usage"] = {"days": {"2026-10-19": 45, "2026-10-20": 3}, "signals": []}  # no carry-over at 45
    settings = Settings(qobuz_skipped=True, accounts=YT.accounts)
    store = store_with([a("acquire", f"t{i}", "new") for i in range(50)], s)
    w = views.limits_what_if("youtube", 45, 0, s, settings, store.prep, TODAY)
    assert w["assessment"] == {"level": 3, "label": "faster"}
    assert (w["allowance_today"], w["remaining_today"], w["days_to_load"]) == (45, 42, 2)


def test_sidebar_warning_dot():
    assert views.sidebar(state(), [], 0, warnings=True)["limits_warning"] is True
    assert views.sidebar(state(), [], 0)["limits_warning"] is False


def test_upgrade_block_of_a_256_kbps_version():
    up = {**UPGRADE, "source": "youtube_music", "source_format": "aac", "status": "not_lossless", "kbps": 256,
          "cutoff_hz": 20000}
    b = views.upgrade_block(up, None, "t1", {"path": "Library/A/not_lossless/x.aiff"})
    assert b["what"] == "256 kbps version" and "256 kbps" in b["quality_line"]
    assert views.upgrade_block(UPGRADE, None, "t1", {"path": "x.aiff"})["what"] == "lossless version"


def test_warning_signs_say_whether_they_are_new_and_when_they_clear():
    s = state()
    s["qobuz_usage"]["signals"] = [
        {"time": "2026-10-07T09:00:00", "kind": "search_failed", "message": "oldest still shown"},
        {"time": "2026-10-19T22:00:00", "kind": "download_rejected", "message": "seen"},
        {"time": "2026-10-20T10:00:00", "kind": "preview_only", "message": "after Got it"}]
    seen = replace(Settings(60), warnings_seen={"qobuz": "2026-10-19T23:00:00"})
    store = store_with([], s)
    sig = views.limits("qobuz", s, seen, store.prep, TODAY)["usage"]["signals"]
    assert [(x["message"], x["new"], x["clears_in"]) for x in sig] == [
        ("oldest still shown", False, 1), ("seen", False, 13), ("after Got it", True, 14)]
    card = views.limit_cards(s, seen, TODAY)[0]
    assert (card["warnings"], card["new_warnings"]) == (3, 1)
    assert views.limit_cards(s, Settings(60), TODAY)[0]["new_warnings"] == 3  # never marked: all new


# --- downloads (Settings and Setup: the source ladder, spec settings-setup §6.4) ---

FAILED = {"ok": False, "problem": "no_premium", "kbps": 160, "at": "2026-10-20T09:00:00"}


def test_downloads_counts_the_library_by_rung():
    s = state(a=e(source="qobuz"),
              b=e("not_lossless", source="youtube_music", source_kbps=256),
              c=e("not_lossless", source="youtube", source_kbps=130),
              d=e("not_lossless", source="soundcloud", source_kbps=None),
              f=e(source="soundcloud", source_kbps=None),  # an artist's lossless original: not a free stream
              g=e(source="qobuz", in_playlists=False),
              h=e("not_lossless", source="youtube", source_kbps=130, hidden=True))
    d = views.downloads(s, Settings(), True, {}, TODAY)
    assert d["library"] == {"lossless": 2, "account": 1, "free": 2}
    assert d["qobuz"] == {"state": "on", "last_check": None, "tracks": 1}
    assert d["youtube"] == {"state": "off", "browser": None, "browser_name": None, "profile": None,
                            "profile_name": None, "last_check": None, "tracks": 1}


def test_downloads_states_from_settings_and_checks():
    yt = Account("chrome", 30, profile="Profile 2", last_check=FAILED)
    sc = Account("firefox", 60, last_check={**FAILED, "problem": "not_logged_in"})
    d = views.downloads(state(), Settings(qobuz_skipped=True, accounts={"youtube": yt, "soundcloud": sc}), False,
                        {"youtube": "DJ"}, TODAY)
    assert d["qobuz"]["state"] == "skipped"
    assert d["youtube"]["state"] == "no_premium" and d["youtube"]["profile_name"] == "DJ"
    assert d["youtube"]["browser_name"] == "Chrome" and d["youtube"]["last_check"] == FAILED
    assert d["soundcloud"]["state"] == "off"  # its last check found no login
    unreadable = Account("safari", 30, last_check={**FAILED, "problem": "cookies_unreadable"})
    assert views.downloads(state(), Settings(accounts={"youtube": unreadable}), True, {},
                           TODAY)["youtube"]["state"] == "unreadable"


def test_downloads_qobuz_off_when_not_signed_in_or_rejected():
    assert views.downloads(state(), Settings(), False, {}, TODAY)["qobuz"]["state"] == "off"
    rejected = Settings(qobuz_last_check={"ok": False, "problem": "login_failed", "kbps": None, "at": "x"})
    assert views.downloads(state(), rejected, True, {}, TODAY)["qobuz"]["state"] == "off"


def test_downloads_paused_and_used_up():
    s = state()
    s["youtube_usage"] = {"days": {"2026-10-20": 3}, "signals": [
        {"time": "2026-10-20T10:01:00", "kind": "auto_stop", "message": "y"}]}
    s["soundcloud_usage"] = {"days": {"2026-10-20": 500}, "signals": []}  # past any carry-over
    d = views.downloads(s, BOTH, True, {}, TODAY)
    assert d["youtube"]["state"] == "paused" and d["soundcloud"]["state"] == "used_up"
    assert d["qobuz"]["state"] == "on"


# --- tidy-up words (plan library stage 2, I5, I6) ---

def test_folder_of():
    assert views.folder_of("Library/F/x.aiff") == "F"
    assert views.folder_of("Library/x.aiff") == ""
    assert views.folder_of("Library/F/not_lossless/x.aiff") == "F/not_lossless"


@pytest.mark.parametrize("reason, detail, kw, text", [
    ("offline", None, {}, "Offline, skipped"),
    ("not_found", None, {}, "Not where Discjockey last saw it"),
    ("name_taken", None, {"to": "Powertrance"}, "A file with this name is already in Powertrance"),
    ("name_taken", None, {"to": ""}, "A file with this name is already in Library"),
    ("changed", None, {}, "Changed since the list was shown"),
    ("failed", "the drive is full", {}, "Couldn't move it: the drive is full"),
    ("stopped", None, {}, "Not moved: the moves were stopped first"),
    ("moved_on", None, {}, "Moved or changed since"),
    ("moved_on", None, {"old": "Old", "new": "New"}, "The folder New isn't there any more"),
    ("place_taken", None, {}, "Another file is in its old place now"),
    ("place_taken", "folder_there", {"old": "Old", "new": "New"}, "A folder called Old is in your Library again."),
    ("place_taken", "name_used", {"old": "Old", "new": "New"}, "Another playlist is called Old now."),
    ("place_taken", None, {"old": "Old", "new": "New"}, "A folder or another playlist is called Old now."),
    ("playlist_renamed", None, {"old": "Old", "new": "New"}, "The playlist isn't called New any more"),
    ("name_taken", "folder_taken", {"to": "New", "frm": "Old"}, "A folder called New is already in your Library."),
    ("changed", "folder_in_use", {"to": "New", "frm": "Old"}, "Old is still the folder of another playlist."),
    ("not_found", "no_folder", {"to": "New", "frm": "Old"}, "Not where Discjockey last saw it"),
])
def test_skip_text(reason, detail, kw, text):
    assert views.skip_text(reason, detail, **{"to": "X", **kw}) == text


def tidy_state():
    return state(
        a=e(title="A", path="Library/Old/a.aiff", file_id=1, placed_by="app", folder="New"),
        b=e(title="B", path="Library/Old/b.aiff", file_id=2, placed_by="user", folder="New"),
        c=e(title="C", path="Library/Old/c.aiff", file_id=3, placed_by="import", folder="New"),
        d=e(title="D", path="Library/Old/d.aiff", file_id=4, placed_by="app", folder="New", online=False))


def tidy_of(st):
    st["files"] = [x["path"] for x in st["tracks"].values()]
    return views.tidy_preview(tidy_rows(st), st)


def test_tidy_preview_ticks_follow_placed_by_and_yours_is_marked():
    p = tidy_of(tidy_state())
    by = {r["track_id"]: r for r in p["rows"]}
    assert [(k, r["ticked"], r["yours"]) for k, r in by.items()] == [
        ("a", True, False), ("b", False, True), ("c", False, True), ("d", False, False)]
    assert (by["a"]["file_id"], by["a"]["from"], by["a"]["to"], by["a"]["from_path"], by["a"]["by_rename"]) == (
        1, "Old", "New", "Library/Old/a.aiff", None)
    assert by["a"]["skip"] is None and by["a"]["title"] == "A"
    assert by["d"]["skip"] == {"reason": "offline", "text": "Offline, skipped"}
    assert p["ticked"] == 1 and p["empty"] is None
    assert p["rekordbox"] == ["rekordbox may show the moved tracks as missing.",
                              "Its Relocate finds them again by file name: Discjockey never renames them."]
    assert p["undo_note"] == "You can undo this on this page."
    assert p["yours"] == {"count": 2, "movable": 2, "mark": "You put this here", "header": "You put these here",
                          "control": "Put these in playlist order too"}


def test_tidy_preview_empty_and_only_yours():
    assert views.tidy_preview([], state())["empty"] == "Every file is where the playlist order puts it."
    assert views.tidy_preview([], state())["yours"] is None
    st = tidy_state()
    del st["tracks"]["a"]
    del st["tracks"]["d"]
    p = tidy_of(st)
    assert p["ticked"] == 0
    assert p["empty"] == "2 files are where you put them, not where the playlist order puts them."
    del st["tracks"]["c"]
    assert tidy_of(st)["empty"] == "1 file is where you put it, not where the playlist order puts it."


def test_tidy_preview_with_only_rows_that_cannot_move_has_no_empty_text():
    st = tidy_state()
    for k in "abc":
        del st["tracks"][k]
    p = tidy_of(st)
    assert p["ticked"] == 0 and p["empty"] is None and p["rows"][0]["skip"]["reason"] == "offline"


def batch(id=1, by="tidy", moved=3, skipped=0, about=None, undoes=None, **kw):
    return BatchRow(id, "2026-10-24T10:00:00", "2026-10-24T10:00:05", by, about, undoes, moved, skipped,
                    kw.get("undoable", moved), kw.get("undone_by"))


def test_batch_titles_and_summaries():
    rows = [batch(4, "undo", undoes=3), batch(3, "rename", about={"from": "Old", "to": "New"}, skipped=2),
            batch(2, "save", moved=1), batch(1, "tidy", moved=0)]
    out = views.move_batches(rows, 7)
    assert out["total"] == 7
    assert [b["title"] for b in out["batches"]] == ["Undo of: Renamed Old to New", "Renamed Old to New",
                                                    "Saved playlists", "Tidy-up"]
    assert [b["summary"] for b in out["batches"]] == ["3 files moved", "3 files moved \u00b7 2 not moved",
                                                       "1 file moved", "0 files moved"]
    assert out["batches"][0] == {"id": 4, "at": "2026-10-24T10:00:00", "title": "Undo of: Renamed Old to New",
                                 "moved": 3, "skipped": 0, "undoable": 3, "undone_by": None,
                                 "summary": "3 files moved"}
    assert views.move_batches([batch(5, "undo", undoes=1)], 9)["batches"][0]["title"] == "Undo"  # older one not listed
    assert views.batch_title(batch(5, "undo", undoes=1), "Tidy-up") == "Undo of: Tidy-up"
    older = views.move_batches([batch(6, "undo", undoes=1), batch(5, "undo", undoes=4), batch(4, "save")], 9,
                               {1: "Tidy-up"})
    assert [b["title"] for b in older["batches"]] == ["Undo of: Tidy-up", "Undo of: Saved playlists",
                                                      "Saved playlists"]
    assert views.batch_title(batch(6, "rename")) == "Renamed a folder"


def move_row(id, kind="file", reason=None, detail=None, src="Library/A/x.aiff", dst="Library/B/x.aiff"):
    return MoveRow(id, 1, id, kind, None, "Artist - Song", src, dst, None, None, None, "skipped", reason, detail,
                   None, None)


def test_batch_result_headlines_and_skips():
    ok = views.batch_result(BatchResult(1, "tidy", 3, (), False), "Tidy-up")
    assert ok == {"batch_id": 1, "title": "Tidy-up", "moved": 3, "headline": "Moved 3 files.", "skipped": [],
                  "stopped": False}
    assert views.batch_result(BatchResult(1, "tidy", 1, (), False), "Tidy-up")["headline"] == "Moved 1 file."
    back = views.batch_result(BatchResult(2, "undo", 2, (), False), "Undo of: Tidy-up")
    assert back["headline"] == "Moved 2 files back."
    assert views.batch_result(BatchResult(2, "undo", 1, (), False), "x")["headline"] == "Moved 1 file back."
    r = views.batch_result(BatchResult(3, "tidy", 1, (
        move_row(1, reason="failed", detail="the drive is full"),
        move_row(2, reason="name_taken", dst="Library/x.aiff")), True), "Tidy-up")
    assert r["headline"] == "Moved 1 file. 2 not moved:" and r["stopped"]
    assert r["skipped"] == [
        {"label": "Artist - Song", "from": "A", "to": "B", "reason": "failed",
         "text": "Couldn't move it: the drive is full"},
        {"label": "Artist - Song", "from": "A", "to": "", "reason": "name_taken",
         "text": "A file with this name is already in Library"}]


def pm(kind="file", skip=None, src="Library/B/x.aiff", dst="Library/A/x.aiff", label="Artist - Song"):
    return PlannedMove(kind, None if kind == "folder" else 1, label, src, dst, None, None, None, skip)


def test_undo_preview_of_files():
    b = batch(1, "tidy")
    p = views.undo_preview(b, [pm(), pm(), pm(skip=("moved_on", None)), pm(skip=("place_taken", None))])
    assert (p["batch_id"], p["title"], p["moving"], p["nothing_left"]) == (1, "Tidy-up", 2, False)
    assert p["warning"] == ["2 files go back to where they were. rekordbox may show them as missing again; "
                            "Relocate finds them by file name."]
    assert [(r["from"], r["to"], r["skip"] and r["skip"]["text"]) for r in p["rows"]] == [
        ("B", "A", None), ("B", "A", None), ("B", "A", "Moved or changed since"),
        ("B", "A", "Another file is in its old place now")]
    one = views.undo_preview(b, [pm()])
    assert one["warning"] == ["1 file goes back to where it was. rekordbox may show it as missing again; "
                              "Relocate finds it by file name."]
    nothing = views.undo_preview(b, [pm(skip=("moved_on", None))])
    assert nothing["nothing_left"] and nothing["moving"] == 0 and nothing["warning"] == []
    assert views.undo_preview(b, [])["nothing_left"]


def test_undo_preview_rows_say_their_kind_and_a_folder_its_files():
    b = batch(2, "rename", moved=7, about={"from": "Old", "to": "New"})
    p = views.undo_preview(b, [pm(), PlannedMove("folder", None, "New", "Library/New", "Library/Old", None, None, None,
                                                  None, 7)])
    assert [(r["kind"], r["files"]) for r in p["rows"]] == [("file", None), ("folder", 7)]  # none on disk: the count it carried
    assert p["moving"] == 8
    inside = [f"Library/New/{i}.aiff" for i in range(9)]  # nine are in it now
    assert views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old")], inside)["rows"][0]["files"] == 9


def test_undo_preview_of_a_folder_rename():
    b = batch(2, "rename", moved=1, about={"from": "Old", "to": "New"})
    inside = ["Library/New/a.aiff", "Library/New/not_lossless/b.aiff", "Library/Newer/c.aiff", "Library/Other/d.aiff"]
    p = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", label="New")], inside)
    assert p["title"] == "Renamed Old to New" and p["moving"] == 2 and not p["nothing_left"]
    assert p["warning"] == ["2 files go back to where they were. rekordbox may show them as missing again; Relocate "
                            "finds them by file name.",
                            "The folder goes back to its old name Old, with everything in it, and the playlist is "
                            "called Old again."]
    assert p["rows"] == [{"label": "New", "kind": "folder", "from": "New", "to": "Old", "files": 2, "skip": None}]
    gone = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", label="New",
                                     skip=("playlist_renamed", None))], inside)
    assert gone["nothing_left"] and gone["warning"] == []
    assert gone["rows"][0]["skip"] == {"reason": "playlist_renamed", "text": "The playlist isn't called New any more"}
    taken = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", skip=("place_taken", "folder_there")),
                                   pm("folder", src="Library/New", dst="Library/Old", skip=("place_taken", "name_used")),
                                   pm("folder", src="Library/New", dst="Library/Old", skip=("moved_on", None))])
    assert [r["skip"]["text"] for r in taken["rows"]] == [
        "A folder called Old is in your Library again.", "Another playlist is called Old now.",
        "The folder New isn't there any more"]


def test_change_file_missing_from_disk_is_on_the_tidy_list_only():
    st = {**PL_STATE, "files": [f for f in PL_FILES if not f.endswith("/b.aiff")]}
    c = call_change(OLD, [OLD[1], OLD[0]], PL_TRACKS, st, st["files"], TODAY, MONEY)
    assert c["kind"] == "moves" and c["headline"] == "2 files would sit in a different folder"
    assert {r["track_id"]: r["skip"] and r["skip"]["reason"] for r in c["tidy"]["rows"]} == {
        "b": "not_found", "c": None}
    assert c["reroutes"] == []


def test_change_of_a_file_outside_the_library_is_no_tidy_up():
    outside = {**PL_STATE["tracks"]["b"], "path": "Elsewhere/Hard_Bounce/b.aiff"}
    st = {**PL_STATE, "tracks": {**PL_STATE["tracks"], "b": outside},
          "files": PL_FILES + ["Elsewhere/Hard_Bounce/b.aiff"]}
    c = call_change(OLD, [OLD[1], OLD[0]], {ID1: [t("a"), t("b")], ID2: [t("b"), t("d")]}, st, st["files"],
                              TODAY, MONEY)
    assert c["tidy"] is None and c["kind"] == "none" and c["headline"] == "Nothing changes in your library"
    assert c["checklist"][-1] == "Happens at the next sync, not right away"


def test_a_refused_folder_rename_is_worded_by_its_offer_code():
    rows = [move_row(1, "folder", "name_taken", "folder_taken", src="Library/Old", dst="Library/New"),
            move_row(2, "folder", "changed", "folder_in_use", src="Library/Old", dst="Library/New"),
            move_row(3, "folder", "not_found", "no_folder", src="Library/Old", dst="Library/New")]
    r = views.batch_result(BatchResult(1, "rename", 0, tuple(rows), False), "Renamed Old to New")
    assert [(x["from"], x["to"], x["text"]) for x in r["skipped"]] == [
        ("Old", "New", "A folder called New is already in your Library."),
        ("Old", "New", "Old is still the folder of another playlist."),
        ("Old", "New", "Not where Discjockey last saw it")]
    file_row = move_row(4, reason="changed")  # a file's `changed` keeps its own words
    assert views.batch_result(BatchResult(1, "tidy", 0, (file_row,), False), "x")["skipped"][0]["text"] == \
        "Changed since the list was shown"


def test_a_rename_offer_counts_the_files_of_a_folder_spelled_another_way_on_disk():
    files = ["Library/Hard_Bounce/a.aiff", "Library/Hard_Bounce/b.aiff", "Library/Other/c.aiff"]
    items = views._rename_items([("hard_bounce", "Hard Bounce")], [], files, {"Hard_Bounce", "Other"},
                                lambda *a, **k: None)
    assert [(i["files"], i["detail"]) for i in items] == [(2, "One folder move instead of 2 file moves.")]


def test_track_detail_link_is_the_first_fetched_tracks_else_the_keys():
    qobuz = SourceTrack("900000001", "Song", ("Artist",), "Al", None, 180000, None, service="qobuz")
    entry = e("lossless", aliases=["qobuz:900000001"])
    fetched = [FetchedPlaylist(PlaylistLine("A", "p1", 1, "qobuz"), [qobuz], []),
               FetchedPlaylist(PlaylistLine("B", "p2", 2), [t("t1")], [])]
    d = views.track_detail("t1", entry, fetched, TODAY)
    assert d["track_link"] == {"url": "https://open.qobuz.com/track/900000001", "label": "Open in Qobuz"}
    assert d["playlists"] == ["A", "B"]  # a Qobuz track is found by its token, not its bare id
    d = views.track_detail("t1", entry, [], TODAY)  # nothing read yet: the link its key gives
    assert d["track_link"] == {"url": "https://open.spotify.com/track/t1", "label": "Open in Spotify"}
    d = views.track_detail("qobuz:900000001", e("lossless"), [], TODAY)
    assert d["track_link"] == {"url": "https://open.qobuz.com/track/900000001", "label": "Open in Qobuz"}
    assert views.track_detail("soundcloud:1", e("lossless"), [], TODAY)["track_link"] is None


def test_a_qobuz_keyed_ambiguous_song_shows_on_the_todo_and_in_the_preview_under_its_song_key():
    q = SourceTrack("900000001", "Song", ("Artist",), "Al", None, 180000, None, service="qobuz")
    st = state(**{"qobuz:900000001": e("lossless"), "t1": e("lossless")})
    plan = Plan(st, [], [("qobuz:900000001", q, "A", ["Library/A/x.aiff", "Library/B/x.aiff"]),
                         ("t1", q, "A", ["Library/A/y.aiff", "Library/B/y.aiff"])], [])  # t1: linked to the Qobuz track
    store = PreviewStore()
    store.ready(Prepared(None, st, Settings(), plan, None, [], [FetchedPlaylist(PlaylistLine("A", "p", 1, "qobuz"), [q], [])]),
                NOW)
    assert set(views.todo_others(store.prep, None)) == {"qobuz:900000001", "t1"}
    p = views.sync_preview(store, st, Settings(), TODAY, NOW, False)
    assert [r["track_id"] for r in p["ambiguous"]] == ["qobuz:900000001", "t1"]
    assert p["in_playlists"] == 1  # counted by song key


# --- the import: questions, duplicates, own songs, watched folders (plan library stage 4, group 5) ---

from pathlib import Path

from discjockey.models import DupFile, DuplicateGroup, ImportCounts, Question, WatchedFolder


def own(status="lossless", cutoff=None, **kw):
    """A song of the user's own: from an import folder, in no playlist, no folder of its own."""
    return e(status, folder=None, cutoff=cutoff, in_playlists=False, source="manual", file_id=kw.pop("file_id", 7),
             online=True, import_state=kw.pop("import_state", "done"),
             path=kw.pop("path", "/Volumes/Example/Music/Example Artist - Song.aiff"),
             artist="Example Artist", title="Song", **kw)


def question(why="artist", delta=None, song_key="t1", own_key="local:1", file_id=7):
    track = SourceTrack("t1", "Song", ("Example Artist",), "Al", "https://example.com/c.jpg", 200000, None)
    return Question(song_key, track, "A", own_key, file_id, why, delta)


def dup_file(file_id, song_key=None, status="lossless", cutoff=None, online=True, in_playlists=False, usable=True,
             path=None):
    return DupFile(file_id, song_key, path or f"/Volumes/Example/Music/Copy {file_id}.aiff", status, cutoff, "aiff",
                   online, in_playlists, usable)


@pytest.mark.parametrize("why,delta,words", [
    ("artist", None, "Same title, different artist"),
    ("no_artist", None, "Same title, no artist in your file"),
    ("length", 4, "Same artist and title, 4 s longer"),
    ("length", -7, "Same artist and title, 7 s shorter"),
    ("no_length", None, "Same artist and title, the length couldn't be read"),
])
def test_a_question_is_a_todo_item_with_its_pair_and_its_why_in_words(why, delta, words):
    st = state(t1=e("missing", folder="A"), **{"local:1": own()})
    out = views.todo(st, "all", False, {}, TODAY, None, [question(why, delta)])
    assert [g["key"] for g in out["groups"]] == ["same_song"]
    assert (out["groups"][0]["label"], out["groups"][0]["hint"]) == (
        "Is this the same song?", "a file of yours might be a playlist song")
    item = out["groups"][0]["items"][0]
    assert (item["group"], item["detail"], item["track_id"]) == ("same_song", words, "t1")
    pair = item["pair"]
    assert (pair["song_key"], pair["own_key"], pair["why"], pair["delta_s"]) == ("t1", "local:1", why, delta)
    assert pair["track"] == {"artist": "Example Artist", "title": "Song", "duration_s": 200.0, "folder": "A",
                             "link": "https://open.spotify.com/track/t1"}
    assert pair["file"] == {"file_id": 7, "song_key": "local:1",
                            "path": "/Volumes/Example/Music/Example Artist - Song.aiff",
                            "artist": "Example Artist", "title": "Song", "duration_s": 180.0, "quality": "lossless",
                            "quality_label": "LOSSLESS", "online": True, "audio_url": None, "in_playlist": False}
    assert out["chips"]["same_song"] == 1 and out["chips"]["all"] == 1


def test_a_question_holds_its_song_back_from_not_found_and_a_song_without_an_entry_still_shows():
    st = state(t1=e("missing", folder="A"), **{"local:1": own()})
    out = views.todo(st, "all", False, {}, TODAY, None, [question()])
    assert [g["key"] for g in out["groups"]] == ["same_song"]  # not also "Not found"
    fresh = views.todo(state(**{"local:1": own()}), "all", False, {}, TODAY, None, [question()])  # not stored yet
    item = fresh["groups"][0]["items"][0]
    assert (item["track_id"], item["folder"], item["quality"]) == ("t1", "A", "missing")


def test_a_question_whose_own_song_is_gone_is_left_out():
    out = views.todo(state(), "all", False, {}, TODAY, None, [question()])
    assert out["groups"] == [] and out["chips"]["same_song"] == 0 and out["empty"] == "all_lossless"


def test_own_songs_are_on_the_todo_only_as_upgrade_ready():
    up = {"file": "Upgrades ready/x.aiff", "alignment": {"result": "exact"}}
    st = state(**{"local:1": own("not_lossless", cutoff=15000), "local:2": own("fake_lossless", cutoff=16000),
                  "local:3": own("not_lossless", cutoff=20000), "local:4": own("missing"),
                  "local:5": own("not_lossless", cutoff=16000, upgrade=up)})
    out = views.todo(st, "all", False, {"local:3": "SEVERAL FILES"}, TODAY)
    assert [(g["key"], [i["track_id"] for i in g["items"]]) for g in out["groups"]] == [
        ("upgrade_ready", ["local:5"])]
    assert out["chips"]["all"] == 1 and out["chips"]["weak"] == 0 and out["chips"]["fake"] == 0
    assert out["groups"][0]["items"][0]["folder"] == ""  # no folder: the page shows none


def test_a_duplicate_group_of_three_files_and_its_words():
    st = state(t1=e(path="/Volumes/Example/Music/Copy 3.aiff", folder="A"),
               **{"local:1": own(file_id=4, path="/Volumes/Example/Music/Copy 4.aiff"),
                  "local:2": own("not_lossless", cutoff=16000, file_id=5, path="/Volumes/Example/Music/Copy 5.aiff")})
    g = DuplicateGroup("dup:3-4-5", "same_song", (3, 4, 5))
    files = {g.id: [dup_file(4, "local:1"), dup_file(3, "t1", in_playlists=True),
                    dup_file(5, "local:2", "not_lossless", 16000)]}
    out = views.todo(st, "all", False, {}, TODAY, None, [], [g], files)
    item = out["groups"][0]["items"][0]
    assert (out["groups"][0]["key"], item["group"], item["detail"]) == ("duplicate", "duplicate",
                                                                       "3 files of the same song")
    assert (item["track_id"], item["pair"]["group_id"], item["pair"]["why"]) == ("dup:3-4-5", "dup:3-4-5", "same_song")
    assert [f["file_id"] for f in item["pair"]["files"]] == [3, 4, 5]  # by file id
    assert [(f["quality"], f["in_playlist"], f["song_key"]) for f in item["pair"]["files"]] == [
        ("lossless", True, "t1"), ("lossless", False, "local:1"), ("weak", False, "local:2")]
    assert item["artist"] == "Artist" and item["in_playlists"] is True  # the playlist song's file names the group
    assert out["chips"]["duplicate"] == 1


def test_the_same_audio_pair_in_both_sources_shows_once_as_the_same_audio():
    st = state(**{"local:1": own(file_id=4), "local:2": own(file_id=5)})
    from_plan = DuplicateGroup("dup:4-5", "same_song", (4, 5))
    from_records = DuplicateGroup("dup:4-5", "same_audio", (4, 5))
    files = {"dup:4-5": [dup_file(4, "local:1"), dup_file(5, "local:2")]}
    for order in ([from_plan, from_records], [from_records, from_plan]):
        out = views.todo(st, "all", False, {}, TODAY, None, [], order, files)
        items = [i for g in out["groups"] for i in g["items"]]
        assert [(i["pair"]["group_id"], i["pair"]["why"], i["detail"]) for i in items] == [
            ("dup:4-5", "same_audio", "The same audio in 2 files")]
        assert out["chips"]["duplicate"] == 1


def test_a_duplicate_group_with_a_file_offline_held_or_gone_is_not_shown():
    st = state(**{"local:1": own(file_id=4), "local:2": own(file_id=5)})
    g = DuplicateGroup("dup:4-5", "same_audio", (4, 5))
    for files in ([dup_file(4, "local:1"), dup_file(5, "local:2", online=False)],
                  [dup_file(4, "local:1"), dup_file(5, "local:2", usable=False)],
                  [dup_file(4, "local:1")], []):
        out = views.todo(st, "all", False, {}, TODAY, None, [], [g], {g.id: files})
        assert out["groups"] == [] and out["chips"]["duplicate"] == 0 and out["empty"] == "all_lossless"


def test_a_duplicate_group_with_a_file_in_a_folder_away_now_is_neither_listed_nor_counted():
    st = state(**{"local:1": own(file_id=4), "local:2": own(file_id=5)})
    g = DuplicateGroup("dup:4-5", "same_audio", (4, 5))
    files = {g.id: [dup_file(4, "local:1"), dup_file(5, "local:2", path="/Volumes/Example/Other/b.aiff")]}
    here = views.todo(st, "duplicate", False, {}, TODAY, None, [], [g], files, away={})
    assert here["chips"]["duplicate"] == 1 and here["chips"]["all"] == 1 and len(here["groups"]) == 1
    for filt in ("all", "duplicate"):
        for why in ("unmounted", "missing"):  # the rows still say online: no scan has seen the folder go
            out = views.todo(st, filt, False, {}, TODAY, None, [], [g], files, away={"/Volumes/Example/Other": why})
            assert out["groups"] == [] and out["chips"]["duplicate"] == 0 and out["chips"]["all"] == 0
    # the sidebar's known-there groups: the api only passes them as counted when nothing is away
    out = views.todo(st, "all", False, {}, TODAY, None, [], [g], {}, counted={g.id})
    assert out["chips"]["all"] == 1 and out["groups"] == []


def test_a_filter_keeps_only_its_group():
    st = state(t1=e("missing"), **{"local:1": own()})
    q = [question()]
    assert [g["key"] for g in views.todo(st, "same_song", False, {}, TODAY, None, q)["groups"]] == ["same_song"]
    out = views.todo(st, "duplicate", False, {}, TODAY, None, q)
    assert out["groups"] == [] and out["empty"] == "nothing_here"


def test_the_library_marks_files_whose_sound_is_not_checked_yet_and_copes_with_own_songs():
    st = state(a=e(), **{"local:1": own(import_state="identified"), "local:2": own(file_id=8)})
    out = views.library(st, "all", None, "", "all", "folder", lines=[])
    assert {r["track_id"]: r["sound_checked"] for r in out["rows"]} == {"a": True, "local:1": False, "local:2": True}
    assert [r["folder"] for r in out["rows"] if r["track_id"].startswith("local")] == ["", ""]
    assert views.library(st, "folder", "Library/A", "", "all", "artist", lines=[])["summary"]["tracks"] == 1  # own songs are in no folder
    assert views.library(st, "unlisted", None, "", "all", "artist", lines=[])["summary"]["tracks"] == 2
    sb = views.sidebar(st, [Row("A", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd")], 0)
    assert (sb["all_tracks"], sb["not_in_playlist"], [p["songs"] for p in sb["playlists"]],
            sb["library_folders"]) == (3, 2, [None], [])


def test_sync_preview_counts_the_songs_waiting_for_an_answer_and_the_checks_left_for_later():
    st = state(t1=e("missing"), **{"local:1": own()})
    plan = Plan(st, [], [], [], questions=[question(), question(song_key="t2", own_key="local:2")], deferred_checks=40)
    store = PreviewStore()
    store.ready(Prepared(None, st, Settings(), plan, None, [], []), NOW)
    p = views.sync_preview(store, st, Settings(), TODAY, NOW, False)
    assert (p["waiting_answers"], p["deferred_checks"]) == (2, 40)
    none = views.sync_preview(PreviewStore(), st, Settings(), TODAY, NOW, False)
    assert (none["waiting_answers"], none["deferred_checks"]) == (0, 0)


def test_the_watched_folders_with_their_states_counts_and_unreadable_files():
    lib = WatchedFolder(1, Path("/m/Library"), "library")
    one = WatchedFolder(2, Path("/Volumes/Example/Music"), "import")
    two = WatchedFolder(3, Path("/Volumes/Gone"), "import")
    counts = {2: ImportCounts(120, 20, 5, 2), 3: ImportCounts(7, 7, 0, 0)}
    unreadable = [(Path("/Volumes/Example/Music/Sub/bad.aiff"), "macOS doesn't let Discjockey read it")]

    def view(phase, stopped=False, away={3: "unmounted"}):
        return views.watched_folders([lib, one, two], counts, away, 500, unreadable, 25, stopped, phase)

    out = view(None)
    assert out["folders"] == [
        {"id": 1, "path": "/m/Library", "name": "Library", "kind": "library", "state": "online", "files": 500,
         "waiting": 0, "unreadable": 0, "crates": [], "too_many": False},
        {"id": 2, "path": "/Volumes/Example/Music", "name": "Music", "kind": "import", "state": "online",
         "files": 120, "waiting": 25, "unreadable": 2, "crates": [], "too_many": False},
        {"id": 3, "path": "/Volumes/Gone", "name": "Gone", "kind": "import", "state": "offline", "files": 7,
         "waiting": 7, "unreadable": 0, "crates": [], "too_many": False}]
    assert out["unreadable"] == [{"folder_id": 2, "path": "/Volumes/Example/Music/Sub/bad.aiff",
                                  "reason": "macOS doesn't let Discjockey read it"}]
    assert (out["waiting"], out["stopped"]) == (25, False)
    assert [r["state"] for r in view("scan")["folders"]] == ["scanning", "scanning", "offline"]
    assert [r["state"] for r in view("tags")["folders"]] == ["online", "importing", "offline"]
    assert [r["state"] for r in view("tags", away={})["folders"]] == ["online", "importing", "importing"]
    # a folder that is there but not a folder any more is "missing", not "offline": two states, two sentences
    assert [r["state"] for r in view("tags", away={2: "missing", 3: "unmounted"})["folders"]] == [
        "online", "missing", "offline"]
    assert view(None, stopped=True)["stopped"] is True
    done = views.watched_folders([lib, one], {2: ImportCounts(120, 0, 0, 0)}, {}, 500, [], 0, False, "link")
    assert [r["state"] for r in done["folders"]] == ["online", "online"]  # nothing of it left to import



def test_a_file_side_hands_its_file_id_to_the_player():
    seen = []
    st = state(t1=e("missing", folder="A"), **{"local:1": own()})
    out = views.todo(st, "all", False, {}, TODAY, None, [question()], audio=lambda key, e: seen.append((key, e)) or "u")
    assert seen == [("local:1", {"path": "/Volumes/Example/Music/Example Artist - Song.aiff", "file_id": 7})]
    assert out["groups"][0]["items"][0]["pair"]["file"]["audio_url"] == "u"



def test_a_stale_question_does_not_hide_its_playlist_song_from_not_found():
    st = state(t1=e("missing", folder="A"))  # the question's own song is gone from the records
    out = views.todo(st, "all", False, {}, TODAY, None, [question()])
    assert [g["key"] for g in out["groups"]] == ["not_found"] and out["chips"]["all"] == 1
    st = state(t1=e("missing", folder="A"), **{"local:1": own()})  # a live one still holds it
    out = views.todo(st, "all", False, {}, TODAY, None, [question()])
    assert [g["key"] for g in out["groups"]] == ["same_song"] and out["chips"]["all"] == 1


def test_counted_duplicate_groups_count_without_files_and_are_not_listed():
    from discjockey.models import DuplicateGroup
    g = DuplicateGroup("dup:3-4", "same_audio", (3, 4))
    st = state(t1=e("lossless", folder="A"))
    plain = views.todo(st, "all", False, {}, TODAY, None, [], [g])
    assert plain["chips"]["duplicate"] == 0 and plain["chips"]["all"] == 0  # no files loaded: nothing to act on
    counted = views.todo(st, "all", False, {}, TODAY, None, [], [g], counted={"dup:3-4"})
    assert counted["chips"]["all"] == 1 and counted["chips"]["duplicate"] == 0 and counted["groups"] == []


def test_the_library_row_counts_its_own_waiting_and_unreadable_files():
    lib = WatchedFolder(1, Path("/m/Library"), "library")
    one = WatchedFolder(2, Path("/Volumes/Example/Music"), "import")
    counts = {1: ImportCounts(500, 3, 1, 2), 2: ImportCounts(120, 20, 5, 0)}
    unreadable = [(Path("/m/Library/House/bad.aiff"), "macOS doesn't let Discjockey read it"),
                  (Path("/m/Library/worse.wav"), "Discjockey can't find sound it can read in it")]
    out = views.watched_folders([lib, one], counts, (), 500, unreadable, 29, False, None)
    assert out["folders"][0] == {"id": 1, "path": "/m/Library", "name": "Library", "kind": "library",
                                 "state": "online", "files": 500, "waiting": 4, "unreadable": 2, "crates": [],
                                 "too_many": False}
    assert out["folders"][1]["waiting"] == 25 and out["folders"][1]["unreadable"] == 0
    assert [(u["folder_id"], u["path"]) for u in out["unreadable"]] == [(1, "/m/Library/House/bad.aiff"),
                                                                        (1, "/m/Library/worse.wav")]


# --- a file of the user's own is not a bought file ---

def test_the_detail_of_an_own_file_says_so_and_shows_the_day_it_was_first_seen():
    entry = own(placed_by="import", first_seen="2026-10-25T12:00:00", source_format="pcm_s16le", added=None)
    d = views.track_detail("local:1", entry, [], TODAY)
    assert d["source_full"] == "your own file" and d["source_name"] == "own file"
    assert d["quality_line"] == "Your own file (PCM) · verified lossless"
    assert d["added"] == "2026-10-25T12:00:00"
    assert views.track_row("local:1", entry)["added"] == "2026-10-25T12:00:00"


def test_track_row_says_whether_a_file_is_the_users_own():
    # the table dims a row only when it is in no playlist and not an own file: the engine says which is which
    assert views.track_row("local:1", own(placed_by="import"))["own"] is True
    assert views.track_row("t1", e("lossless", source="manual", placed_by="app"))["own"] is False  # bought
    assert views.track_row("t2", e("not_lossless", source="youtube", cutoff=16000, in_playlists=False))["own"] is False


def test_a_bought_file_the_sync_adopted_stays_bought_with_its_own_added_day():
    entry = e("lossless", source="manual", source_format="pcm_s16be", placed_by="app", first_seen="2026-10-25T12:00:00",
              added="2026-10-01T10:00:00")
    d = views.track_detail("t1", entry, [], TODAY)
    assert d["source_full"] == "bought" and d["source_name"] == "bought" and d["added"] == "2026-10-01T10:00:00"
    assert d["quality_line"].startswith("bought file ")
    without = e("lossless", source="manual", placed_by="app", first_seen="2026-10-25T12:00:00", added=None)
    assert views.track_row("t1", without)["added"] is None  # first_seen stands in for an own file only


def test_files_whose_sound_is_not_checked_yet_are_left_out_of_every_quality_count():
    st = state(a=e(), b=e("not_lossless", cutoff=16000), **{"local:1": own(import_state="identified"),
                                                           "local:2": own(import_state="identified", file_id=8, path="/x/b.mp3"),
                                                           "local:3": own(file_id=9)})
    out = views.library(st, "all", None, "", "all", "artist", lines=[])
    assert out["summary"]["tracks"] == 5 and out["chips"]["all"] == 5
    assert out["summary"]["by_quality"] == {"lossless": 2, "good_lossy": 0, "weak": 1, "fake": 0, "missing": 0}
    assert out["summary"]["lossless_share"] == round(2 / 3, 4)
    assert (out["chips"]["lossless"], out["chips"]["good_lossy"], out["chips"]["weak"]) == (2, 0, 1)
    assert {r["track_id"] for r in views.library(st, "all", None, "", "lossless", "artist", lines=[])["rows"]} == {"a", "local:3"}
    # sorted by quality they come after every checked file, whatever the direction of the codec's guess
    assert [r["track_id"] for r in views.library(st, "all", None, "", "all", "quality", lines=[])["rows"]][-2:] == ["local:1", "local:2"]


def test_a_playlist_file_whose_sound_is_not_checked_yet_is_not_counted_nor_a_to_do():
    st = state(a=e(), b=e(import_state="identified", source="manual", placed_by="import"))
    assert views.lossless_share(st)["by_quality"]["lossless"] == 1 and views.lossless_share(st)["total"] == 1
    assert views.folder_bars(st, ["A"])[0]["tracks"] == 2
    assert views.folder_bars(st, ["A"])[0]["lossless_share"] == 1.0
    lossy = e("not_lossless", import_state="identified")
    assert views._group(lossy) is None and views._group(e("not_lossless")) == "good_lossy"


def test_the_detail_of_a_file_whose_sound_is_not_checked_yet_says_so():
    d = views.track_detail("local:1", own(import_state="identified", source_format="pcm_s16le", placed_by="import"), [], TODAY)
    assert d["sound_checked"] is False and d["quality_line"] == "Your own file (PCM) · sound not checked yet"
    d = views.track_detail("local:2", own(source_format="pcm_s16le", placed_by="import"), [], TODAY)
    assert d["sound_checked"] is True and d["quality_line"] == "Your own file (PCM) · verified lossless"
    assert views.track_detail("t1", e(), [], TODAY)["sound_checked"] is True


def test_a_file_in_an_import_folder_that_is_away_now_is_offline_or_in_a_folder_not_found():
    mine = e("lossless", path="/Volumes/Example Drive/Music/x.wav", online=True)
    other = e("lossless", path="/Volumes/Example Drive 2/x.wav", online=True)
    file_state = lambda entry, away, **kw: views.track_detail("t1", entry, [], TODAY, away=away, **kw)["file_state"]
    unplugged, renamed = {"/Volumes/Example Drive": "unmounted"}, {"/Volumes/Example Drive": "missing"}
    assert file_state(mine, unplugged) == "offline" and file_state(mine, renamed) == "folder_missing"
    assert file_state(other, unplugged) == "here"  # another folder, same name start
    assert file_state(mine, {}) == "here" and file_state(mine, None) == "here"
    stored = e("lossless", path="/Volumes/Elsewhere/x.wav", online=False)
    assert file_state(stored, unplugged) == "offline"  # a stored 0 stays offline
    assert file_state(e("missing"), unplugged) == "here"  # no file, nothing away
    inner = {"/Volumes/Example Drive": "unmounted", "/Volumes/Example Drive/Music": "missing"}
    assert file_state(mine, inner) == "folder_missing"  # the innermost watched folder decides
    assert file_state(mine, renamed, exists=False) == "folder_missing"  # the folder comes before the file


def test_library_rows_say_whether_their_file_is_here_offline_or_in_a_folder_not_found():
    st = {"tracks": {"local:1": own(path="/Volumes/Example Stick/Music/a.aiff"),
                     "local:2": {**own(path="/Volumes/Example Stick/Music/b.aiff"), "online": False},
                     "local:3": own(path="/Users/you/Old Music/c.aiff"),
                     "t1": e("lossless")}}

    def states(away):
        return {r["track_id"]: r["file_state"] for r in views.library(st, "all", None, "", "all", "title", away=away, lines=[])["rows"]}

    # no folder away: only the row a scan stored as offline is, read as the panel reads it (file_state)
    assert states(None) == {"local:1": "here", "local:2": "offline", "local:3": "here",
                            "t1": "here"}
    assert states({"/Volumes/Example Stick/Music": "unmounted"}) == {
        "local:1": "offline", "local:2": "offline", "local:3": "here", "t1": "here"}
    assert states({"/Users/you/Old Music": "missing"}) == {
        "local:1": "here", "local:2": "offline", "local:3": "folder_missing", "t1": "here"}
    # decided per folder: a row never asks whether its own file is there, so "file_missing" stays the panel's
    assert "file_missing" not in states({"/Volumes/Example Stick/Music": "missing"}).values()

# --- crates (plan library stage 5, D8) ---

W = "/Volumes/Example Drive/Crates"
OTHER = "/Users/dj/Music/Sets"


def under(root, *folders):
    return [f"{root}/{folder}/Example Artist - Song.aiff" for folder in folders]


def crate_rows(files, watched=(W,), overrides=None, root=W):
    return views.crates(files, list(watched), overrides or {})[root]["crates"]


def test_a_crate_is_a_folder_that_holds_a_file_and_a_wrapper_gets_no_row():
    files = [f"{W}/Example Artist - Root.aiff", *under(W, "Old Sets/Bounce", "Old Sets/Bounce/Peak", "Techno")]
    got = views.crates(files, [W], {})[W]
    assert [(c["label"], c["files"], c["has_crates"]) for c in got["crates"]] == [
        ("Bounce", 2, True), ("Bounce › Peak", 1, False), ("Techno", 1, False)]  # "Old Sets" holds no file itself
    assert (got["too_many"], got["crate_count"]) == (False, 3)
    assert [c["tip"] for c in got["crates"]] == ["Crates › Old Sets › Bounce", "Crates › Old Sets › Bounce › Peak",
                                                 "Crates › Techno"]
    assert [c["path"] for c in got["crates"]][0] == f"{W}/Old Sets/Bounce"


def test_files_in_the_watched_folder_itself_belong_to_no_crate():
    got = views.crates([f"{W}/Example Artist - Song.aiff"], [W], {})
    assert got == {W: {"too_many": False, "crate_count": 0, "crates": []}}
    assert views.crates([], [W, OTHER], {}) == {W: got[W], OTHER: got[W]}  # every watched folder has its entry


def test_crates_count_the_files_at_or_below_them_and_a_prefix_is_not_a_parent():
    files = under(W, "Hard", "Hard", "Hard/2019", "Hard 2")
    assert [(c["label"], c["files"]) for c in crate_rows(files)] == [("Hard", 3), ("Hard 2", 1), ("Hard › 2019", 1)]


def test_a_crate_in_a_crate_reads_its_nearest_crate_ancestor_then_its_own_name():
    files = under(W, "Hardtechno", "Hardtechno/2019", "Hardtechno/2019/Peak", "Wrapper/Deep/House")
    assert [c["label"] for c in crate_rows(files)] == [
        "2019 › Peak", "Hardtechno", "Hardtechno › 2019", "House"]  # a wrapper in the way changes nothing


def test_crates_sharing_a_name_read_with_their_parent_folder_in_one_watched_folder_and_in_two():
    files = under(W, "Old Sets/Bounce", "New Sets/Bounce", "Techno") + under(OTHER, "bounce", "Tech")
    got = views.crates(files, [W, OTHER], {})
    assert [c["label"] for c in got[W]["crates"]] == ["Bounce · New Sets", "Bounce · Old Sets", "Techno"]
    assert [c["label"] for c in got[OTHER]["crates"]] == ["bounce · Sets", "Tech"]  # fold-equal across watched folders
    # a crate inside another crate has a many-name label and is not compared with the single-name ones
    nested = under(W, "Bounce", "Bounce/Peak", "Peak")
    assert [c["label"] for c in crate_rows(nested)] == ["Bounce", "Bounce › Peak", "Peak"]


def test_crates_come_in_natural_case_folded_label_order():
    files = under(W, "Set 10", "set 2", "Set 1", "Zeta", "alpha")
    assert [c["label"] for c in crate_rows(files)] == ["alpha", "Set 1", "set 2", "Set 10", "Zeta"]


def test_a_label_never_changes_with_what_is_hidden():
    files = under(W, "Old Sets/Bounce", "New Sets/Bounce")
    shown = crate_rows(files)
    hidden = crate_rows(files, overrides={f"{W}/Old Sets/Bounce": False})
    assert [c["label"] for c in hidden] == [c["label"] for c in shown] == ["Bounce · New Sets", "Bounce · Old Sets"]
    assert [c["hidden"] for c in shown] == [False, False]
    assert [c["hidden"] for c in hidden] == [False, True]
    assert crate_rows(files, overrides={f"{W}/Old Sets/Bounce": True})[1]["hidden"] is False


def test_more_than_25_crates_make_a_too_many_folder_with_every_crate_hidden_unless_switched_on():
    folders = [f"Crate {i:02d}" for i in range(26)]
    got = views.crates(under(W, *folders), [W], {f"{W}/Crate 03": True, f"{W}/Crate 04": False})[W]
    assert (got["too_many"], got["crate_count"], len(got["crates"])) == (True, 26, 26)
    assert {c["name"] for c in got["crates"] if not c["hidden"]} == {"Crate 03"}
    exactly = views.crates(under(W, *folders[:25]), [W], {})[W]
    assert (exactly["too_many"], any(c["hidden"] for c in exactly["crates"])) == (False, False)


def test_a_few_thousand_crates_are_worked_out_in_linear_time():
    # 3000 flat crates, 30 of them with one more inside: the quadratic version took over a minute here, this under a
    # second; the result is checked as well, so a fast wrong answer fails too
    folders = [f"Crate {i:04d}" for i in range(3000)]
    nested = [f"{f}/Inner" for f in folders[:30]]
    start = time.monotonic()
    rows = crate_rows(under(W, *folders, *nested))
    assert time.monotonic() - start < 3
    assert len(rows) == 3030
    assert {r["name"] for r in rows if r["has_crates"]} == set(folders[:30])
    assert not any(r["has_crates"] for r in rows if r["name"] == "Inner" or r["name"] in folders[30:])


def test_a_file_under_two_watched_folders_belongs_to_the_deeper_one():
    inner = f"{W}/Deep"
    got = views.crates(under(inner, "A"), [W, inner], {})
    assert [c["label"] for c in got[W]["crates"]] == [] and [c["tip"] for c in got[inner]["crates"]] == ["Deep › A"]


# --- the sidebar's records, Favourites and watched folders (D3, D5, I4) ---

def record(*tokens, service="spotify"):
    return PlaylistRecord(service, "2026-10-30T10:00:00", tuple(
        RecordedTrack(i, t, "Artist", f"Title {t}", 180000) for i, t in enumerate(tokens, start=1)))


def test_a_playlists_songs_are_the_distinct_songs_of_its_record_and_unread_is_none():
    st = state(a=e(folder="A"), b=e(folder="A", aliases=["sp-b"]), c=e("missing", folder="A"))
    lines = [Row("A", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"),
             Row("B", "https://open.spotify.com/playlist/3DiscjockeyExampleList"),
             Row("C", "https://open.qobuz.com/playlist/900000001", enabled=False),
             Row("D", "https://open.qobuz.com/playlist/900000002")]
    refs = [r.ref for r in lines]
    records = {refs[0]: record("a", "sp-b", "b", "a", "c", "unknown", "unknown"), refs[1]: record(),
               refs[2]: record("a", service="qobuz")}
    out = views.sidebar(st, lines, 0, records=records)["playlists"]
    # a listed twice, "sp-b" is b's alias, "unknown" has no song yet but is one row of the view: a, b, c, unknown
    assert [p["songs"] for p in out] == [4, 0, 1, None]
    assert [p["enabled"] for p in out] == [True, True, False, True]  # a switched-off playlist keeps its number


def test_the_watched_folders_come_by_name_with_place_files_state_and_crates():
    lib = WatchedFolder(1, Path("/m/Library"), "library")
    crates_ = WatchedFolder(2, Path(W), "import")
    sets = WatchedFolder(3, Path(OTHER), "import")
    st = state(a=e(folder="A"), **{
        "local:1": own(path=f"{W}/Hard/Example Artist - Song.aiff"), "local:2": own(path=f"{W}/Example Artist - B.aiff"),
        "local:3": own(path=f"{OTHER}/House/2019/Example Artist - C.aiff"),
        "local:4": own(path=f"{W}Extra/Example Artist - D.aiff")})  # "Crates" is not a parent of "CratesExtra"
    out = views.sidebar(st, [], 0, watched=[lib, crates_, sets], away={2: "unmounted"})["watched"]
    assert [(w["name"], w["place"], w["files"], w["state"], w["too_many"], w["crate_count"]) for w in out] == [
        ("Crates", "Example Drive › Crates", 2, "offline", False, 1), ("Sets", "~/Music/Sets", 1, "here", False, 1)]
    assert out[0]["crates"] == [{"path": f"{W}/Hard", "label": "Hard", "name": "Hard", "tip": "Crates › Hard",
                                 "files": 1, "hidden": False, "has_crates": False}]
    assert views.sidebar(st, [], 0, watched=[sets], away={3: "missing"})["watched"][0]["state"] == "folder_missing"
    assert views.sidebar(st, [], 0)["watched"] == []  # no library.db: nothing watched


def test_place_words_a_folder_as_the_watched_folder_list_does():
    assert views.place("/Users/dj/Music/Sets") == "~/Music/Sets"
    assert views.place("/Users/dj") == "~" and views.place("/Users/dj/") == "~"
    assert views.place("/Volumes/Example Drive") == "Example Drive"
    assert views.place("/Volumes/Example Drive/Music/Old") == "Example Drive › Music/Old"
    assert views.place("/srv/music/Old") == "/srv/music/Old"


def test_favourites_resolve_in_their_stored_order_and_a_gone_key_is_left_out():
    crate = WatchedFolder(2, Path(W), "import")
    st = state(a=e(folder="A"), b=e(folder="Zeta"), c=e(folder="Hard_Bounce"),
               **{"local:1": own(path=f"{W}/Old Sets/Hard/Example Artist - Song.aiff"),
                  "local:2": own(path=f"{W}/Old Sets/Hard/Peak/Example Artist - B.aiff")})
    lines = [Row("Hard_Bounce", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd", enabled=False)]
    ref = lines[0].ref
    keys = [f"folder:{W}/Old Sets/Hard/Peak", "folder:Library/Zeta", f"playlist:{ref}", "playlist:qobuz:1",
            "folder:Library/Gone", f"folder:{W}", "folder:Library/Zeta", "folder:Library/Hard_Bounce"]
    out = views.sidebar(st, lines, 0, records={ref: record("c", "x")}, favourites=keys, watched=[crate],
                        away={2: "unmounted"}, overrides={f"{W}/Old Sets/Hard/Peak": False})["favourites"]
    assert [(f["key"], f["kind"], f["name"], f["count"], f["path"], f["state"]) for f in out] == [
        (f"folder:{W}/Old Sets/Hard/Peak", "folder", "Hard › Peak", 1, f"{W}/Old Sets/Hard/Peak", "offline"),
        ("folder:Library/Zeta", "folder", "Zeta", 1, "Library/Zeta", "here"),
        (f"playlist:{ref}", "playlist", "Hard_Bounce", 2, None, "here"),
        (f"folder:{W}", "folder", "Crates", 2, W, "offline")]  # a hidden crate and a folder in use stay as they are
    assert out[2]["service"] == "spotify" and out[2]["enabled"] is False
    assert views.sidebar(st, lines, 0, favourites=[f"playlist:{ref}"])["favourites"][0]["count"] is None  # never read


# --- the playlist and folder views (plan library stage 5, B3: D6, D9-D12, I4) ---

TECHNO = Row("Techno", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd")
HOUSE = Row("House", "https://open.qobuz.com/playlist/900000001", enabled=False)


def mine(path, status="lossless", artist="Ann", title="Song", **kw):
    """An own file the import found (`own`), named, with its place marked as the import's."""
    return {**own(status, path=path, **kw), "artist": artist, "title": title, "placed_by": "import"}


def song(folder, name, path, **kw):
    return e(folder=folder, artist="Example Artist", title=name, path=path, **kw)


def playlist_state():
    """Techno holds a (own folder), b (in not_lossless/ of Techno), c (sits in House's folder), g (not found); d sits in
    Techno's folder but the playlist doesn't hold it; h sits in House's folder and House holds it."""
    return state(
        a=song("Techno", "One", "Library/Techno/Example Artist - One.aiff", aliases=["alias-a"]),
        b=song("Techno", "Two", "Library/Techno/not_lossless/Example Artist - Two.mp3", status="not_lossless", cutoff=20000),
        c=song("Techno", "Three", "Library/House/Example Artist - Three.aiff"),
        d=song("Techno", "Four", "Library/techno/Example Artist - Four.aiff"),
        g=e("missing", folder="Techno", artist="Example Artist", title="Gone"),
        h=song("House", "Five", "Library/House/Example Artist - Five.aiff"))


def techno_records():
    # alias-a is a's alias and a again at 7, b and c once, g has no file, "unheard" is no song of the library yet
    return {TECHNO.ref: record("a", "b", "alias-a", "c", "g", "unheard", "a"), HOUSE.ref: record("h", "a", service="qobuz")}


def playlist_view(st=None, key="Techno", query="", filt="all", sort=None, **kw):
    return views.library(st or playlist_state(), "playlist", key, query, filt, sort, lines=[TECHNO, HOUSE],
                         records=kw.pop("records", techno_records()), **kw)


def test_a_playlist_lists_its_songs_in_order_each_once_with_a_row_for_a_song_without_a_file():
    out = playlist_view()
    assert [(r["track_id"], r["position"], r["file_state"]) for r in out["rows"]] == [
        ("a", 1, "here"), ("b", 2, "here"), ("c", 4, "here"), ("g", 5, "no_file"), ("unheard", 6, "no_file")]
    assert (out["view"], out["key"], out["folder"], out["title"], out["folder_kind"]) == (
        "playlist", "Techno", "Techno", "Techno", None)
    assert (out["read_at"], out["enabled"], out["service"], out["empty"]) == ("2026-10-30T10:00:00", True, "spotify", None)
    assert views.library(playlist_state(), "playlist", "house", "", "all", None, lines=[TECHNO, HOUSE],
                         records=techno_records())["enabled"] is False


def test_a_song_without_a_file_waits_or_is_not_found():
    rows = {r["track_id"]: r for r in playlist_view()["rows"]}
    assert (rows["g"]["wait"], rows["unheard"]["wait"], rows["a"]["wait"]) == ("not_found", "waiting", None)
    waiting = rows["unheard"]  # the record's own words stand in for the song
    assert (waiting["artist"], waiting["title"], waiting["duration_s"], waiting["quality"]) == (
        "Artist", "Title unheard", 180.0, "missing")
    assert (waiting["place"], waiting["path"], waiting["cover_url"], waiting["playlists"]) == (None, None, None, ["Techno"])
    assert rows["g"]["playlists"] == ["Techno"] and rows["g"]["title"] == "Gone"  # the library's own naming


def test_a_file_outside_the_playlists_folder_says_where_it_sits_and_the_rest_says_nothing():
    rows = {r["track_id"]: r for r in playlist_view()["rows"]}
    assert (rows["a"]["place"], rows["b"]["place"], rows["c"]["place"]) == (None, None, "House")  # not_lossless/ is inside


def test_the_files_of_the_playlists_folder_it_does_not_hold_come_below_as_also():
    out = playlist_view()
    assert [(r["track_id"], r["position"], r["place"]) for r in out["also"]] == [("d", None, None)]  # "techno" is "Techno"
    assert views.library(playlist_state(), "all", None, "", "all", None, lines=[])["also"] is None
    assert [r["track_id"] for r in playlist_view(sort="-title")["also"]] == ["d"]


def test_a_playlists_summary_and_chips_count_its_rows_with_a_file_and_the_search_narrows_rows_and_also():
    out = playlist_view()
    assert out["summary"]["tracks"] == 3 and out["summary"]["by_quality"]["lossless"] == 2
    assert out["chips"] == {"all": 3, "lossless": 2, "good_lossy": 1, "weak": 0, "fake": 0, "upgrade_ready": 0}
    assert out["subtitle"] == ["3 tracks", "Spotify playlist", "Library › Techno"]
    hit = playlist_view(query="four")
    assert ([r["track_id"] for r in hit["rows"]], [r["track_id"] for r in hit["also"]]) == ([], ["d"])
    assert hit["chips"]["all"] == 0 and hit["summary"]["tracks"] == 3 and hit["empty"] is None
    lossy = playlist_view(filt="good_lossy")  # a quality filter leaves out the rows without a file, and the lossless also
    assert ([r["track_id"] for r in lossy["rows"]], lossy["also"]) == (["b"], [])
    nothing = playlist_view(query="zzz")
    assert (nothing["rows"], nothing["also"], nothing["empty"]) == ([], [], "no_match")


def test_a_playlist_sorts_by_its_own_order_and_other_views_fall_back_to_artist():
    assert [r["track_id"] for r in playlist_view(sort="-order")["rows"]] == ["unheard", "g", "c", "b", "a"]
    out = views.library(playlist_state(), "all", None, "", "all", "order", lines=[TECHNO, HOUSE])
    assert [r["title"] for r in out["rows"]] == sorted(r["title"] for r in out["rows"])  # artist, then title


def test_every_row_names_the_playlists_that_hold_the_song_in_playlists_txt_order():
    out = views.library(playlist_state(), "all", None, "", "all", "title", lines=[TECHNO, HOUSE], records=techno_records())
    assert {r["track_id"]: r["playlists"] for r in out["rows"]} == {
        "a": ["Techno", "House"], "b": ["Techno"], "c": ["Techno"], "d": [], "h": ["House"]}


def test_a_playlist_never_read_has_no_rows_but_its_folders_files_and_one_that_is_gone_says_so():
    never = playlist_view(records={})
    assert (never["rows"], never["read_at"], never["empty"], never["subtitle"]) == (
        [], None, None, ["Spotify playlist", "not read yet"])
    assert {r["track_id"] for r in never["also"]} == {"a", "b", "d"}
    gone = playlist_view(key="Nowhere")
    assert (gone["empty"], gone["rows"], gone["also"], gone["subtitle"], gone["read_at"]) == ("gone", [], None, [], None)
    read_empty = playlist_view(records={TECHNO.ref: record()})
    assert (read_empty["rows"], read_empty["read_at"]) == ([], "2026-10-30T10:00:00")


def test_all_tracks_and_not_in_a_playlist_say_where_each_file_sits():
    folder = f"{W}/Hard/2019"
    st = state(a=song("Techno", "One", "Library/Techno/Example Artist - One.aiff"),
               b=song("Techno", "Two", "Library/techno/not_lossless/Example Artist - Two.mp3"),
               **{"local:1": mine(f"{folder}/Example Artist - A.aiff"),
                  "local:2": mine(f"{W}/Example Artist - B.aiff"), "local:6": mine(f"{W}/Hard/Example Artist - F.aiff"),
                  "local:3": mine(f"{OTHER}/Bounce/Example Artist - C.aiff"),
                  "local:4": mine(f"{W}/Old Sets/Bounce/Example Artist - D.aiff"),
                  "local:5": mine(f"{W}/Wrap/Deep/Example Artist - E.aiff")})
    imports = [WatchedFolder(2, Path(W), "import"), WatchedFolder(3, Path(OTHER), "import")]
    out = views.library(st, "all", None, "", "all", "title", lines=[TECHNO], watched=imports)
    assert {r["track_id"]: r["place"] for r in out["rows"]} == {
        "a": "Techno", "b": "Techno", "local:1": "Crates › Hard › 2019", "local:2": "Crates", "local:6": "Crates › Hard", "local:3": "Sets › Bounce · Sets",
        "local:4": "Crates › Bounce · Old Sets", "local:5": "Crates › Deep"}
    unlisted = views.library(st, "unlisted", None, "", "all", "title", lines=[TECHNO], watched=imports)
    assert {r["track_id"] for r in unlisted["rows"]} == {f"local:{i}" for i in range(1, 7)}
    assert unlisted["rows"][0]["place"] is not None


WATCHED = [WatchedFolder(1, Path("/m/Library"), "library"), WatchedFolder(2, Path(W), "import")]


def folder_state():
    return state(
        t=song("Techno", "One", "Library/Techno/Example Artist - One.aiff"),
        n=song("Techno", "Two", "Library/Techno/not_lossless/Example Artist - Two.mp3", status="not_lossless", cutoff=20000),
        x=song("Technology", "Three", "Library/Technology/Example Artist - Three.aiff"),
        **{"local:1": mine(f"{W}/Hard/2019/Example Artist - A.aiff", title="A"),
           "local:2": mine(f"{W}/Hard/Example Artist - B.aiff", title="B"),
           "local:3": mine(f"{W}/Example Artist - C.aiff", title="C"),
           "local:4": mine(f"{W}Extra/Example Artist - D.aiff"),
           "local:5": mine(f"{W}/Wrap/Deep/Example Artist - E.aiff", title="E")})


def folder_view(key, st=None, **kw):
    return views.library(st or folder_state(), "folder", key, "", "all", "title", lines=[TECHNO], watched=WATCHED, **kw)


def test_a_watched_folder_lists_what_lies_at_or_below_it_with_each_files_crate():
    out = folder_view(W)
    assert (out["folder_kind"], out["title"], out["view"], out["key"], out["empty"]) == ("watched", "Crates", "folder", W, None)
    assert {r["track_id"]: r["subfolder"] for r in out["rows"]} == {
        "local:1": "Hard › 2019", "local:2": "Hard", "local:3": "", "local:5": "Deep"}  # "" = the folder itself
    assert out["subtitle"] == ["4 tracks", "3 folders with music", views.place(W)]
    assert out["summary"]["tracks"] == 4 and out["also"] is None


def test_a_crate_lists_its_files_with_the_path_below_it_and_a_deeper_route_still_has_its_view():
    hard = folder_view(f"{W}/Hard")
    assert (hard["folder_kind"], hard["title"], hard["subtitle"]) == ("crate", "Hard", ["2 tracks", "Crates › Hard"])
    assert {r["track_id"]: r["subfolder"] for r in hard["rows"]} == {"local:1": "2019", "local:2": ""}
    wrapper = folder_view(f"{W}/Wrap")  # no crate itself, but a route to it still shows what lies below
    assert (wrapper["folder_kind"], wrapper["title"], wrapper["empty"]) == ("crate", "Wrap", None)
    assert [(r["track_id"], r["subfolder"]) for r in wrapper["rows"]] == [("local:5", "Deep")]
    assert folder_view(f"{W}/Hard/2019")["title"] == "Hard › 2019"  # a crate in a crate reads as its label


def test_a_folder_is_found_by_path_prefix_with_a_boundary_and_by_nfc():
    assert [r["track_id"] for r in folder_view("Library/Techno")["rows"]] == ["t", "n"]  # not Technology
    assert folder_view(f"{W}/Hard/")["summary"]["tracks"] == 2  # a closing slash is the same folder
    umlaut = unicodedata.normalize("NFC", "Süß")
    st = state(**{"local:1": mine(f"{W}/{umlaut}/Example Artist - A.aiff")})
    nfd = unicodedata.normalize("NFD", f"{W}/{umlaut}")
    assert nfd != f"{W}/{umlaut}"
    assert [r["track_id"] for r in folder_view(nfd, st)["rows"]] == ["local:1"]
    assert folder_view(nfd, st)["title"] == umlaut


def test_not_lossless_under_a_library_folder_is_never_a_subfolder():
    out = folder_view("Library/Techno")
    assert (out["folder_kind"], out["subtitle"]) == ("library", ["2 tracks", "Library › Techno"])
    assert {r["track_id"]: (r["subfolder"], r["place"]) for r in out["rows"]} == {"t": (None, "Techno"), "n": (None, "Techno")}
    assert views.library(folder_state(), "folder", "Library/Techno", "", "all", "title", lines=[],
                         watched=WATCHED)["subtitle"] == ["2 tracks", "no playlist uses it", "Library › Techno"]
    assert folder_view("Library/Techno/not_lossless")["folder_kind"] == "library"  # still a view, never a crate


def test_a_folder_that_is_not_there_any_more_is_gone_and_an_empty_watched_folder_is_not():
    for key in ("Library/Nowhere", f"{W}Extra", "/Somewhere/else", f"{W}/Hard/2020", "Library", ""):
        out = folder_view(key)
        assert (out["empty"], out["rows"], out["subtitle"], out["folder_kind"] in (None, "crate", "library")) == (
            "gone", [], [], True), key
    assert folder_view("/Somewhere/else")["folder_kind"] is None
    empty = folder_view(W, state(t=song("Techno", "One", "Library/Techno/Example Artist - One.aiff")))
    assert (empty["empty"], empty["rows"], empty["folder_kind"]) == ("no_match", [], "watched")
    assert empty["subtitle"] == ["0 tracks", views.place(W)]  # no folders with music: that part is left out


def test_an_offline_folder_keeps_its_files_and_says_so_second():
    out = folder_view(f"{W}/Hard", away={W: "unmounted"})
    assert {r["file_state"] for r in out["rows"]} == {"offline"}
    assert out["subtitle"] == ["2 tracks", "Offline: connect the drive", "Crates › Hard"]
    assert folder_view(W, away={W: "missing"})["subtitle"][1] == "Folder not found"
    assert folder_view("Library/Techno", away={W: "missing"})["subtitle"] == ["2 tracks", "Library › Techno"]  # not that one


def test_a_folder_of_own_files_in_no_playlist_counts_its_lossy_files_and_has_nothing_in_the_to_do_list():
    st = state(**{"local:1": mine(f"{OTHER}/Rips/Example Artist - A.mp3", "not_lossless", cutoff=20000),
                  "local:2": mine(f"{OTHER}/Rips/Example Artist - B.mp3", "not_lossless", cutoff=16000),
                  "local:3": mine(f"{OTHER}/Rips/Example Artist - C.aiff")})
    out = views.library(st, "folder", f"{OTHER}/Rips", "", "all", "title", lines=[],
                        watched=[WatchedFolder(3, Path(OTHER), "import")])
    assert out["summary"]["not_lossless"] == 2 and out["summary"]["to_do"] == 0 and out["summary"]["tracks"] == 3
    assert {r["own"] for r in out["rows"]} == {True} and out["folder_kind"] == "crate"


def test_a_folder_view_searches_filters_and_counts_like_the_others():
    out = views.library(folder_state(), "folder", W, "ann", "lossless", "-title", lines=[], watched=WATCHED)
    assert [r["title"] for r in out["rows"]] == ["E", "C", "B", "A"]
    assert out["summary"]["tracks"] == 4 and out["chips"]["all"] == 4


def test_track_detail_carries_the_place_it_is_given():
    assert views.track_detail("t1", e(), [], TODAY, place="Techno")["place"] == "Techno"
    assert views.track_detail("t1", e(), [], TODAY)["place"] is None


# --- stage review of step B: the browser's counts are the views' rows; the playlist's songs; hidden; the order of also ---

def browser_state():
    """Every kind of place at once: a file outside its song's folder (`far`), an own file in a Library folder no song
    uses (`local:9`) and one in a playlist's folder (`local:8`), plus the playlist and folder states."""
    return state(**playlist_state()["tracks"], **folder_state()["tracks"],
                 far=song("Techno", "Far", "Library/Loose/Example Artist - Far.aiff"),
                 **{"local:9": mine("Library/Extra/Example Artist - Own.aiff", title="Own"),
                    "local:8": mine("Library/Techno/Example Artist - Mine.aiff", title="Mine")})


def test_every_count_in_the_browser_is_the_length_of_the_rows_of_the_view_it_opens():
    st, records = browser_state(), {**techno_records(), TECHNO.ref: record("a", "b", "far", "g", "unheard", "a")}
    kw = dict(lines=[TECHNO, HOUSE], records=records, watched=WATCHED)
    side = views.sidebar(st, [TECHNO, HOUSE], 0, records=records, watched=WATCHED)

    def rows(view, key=None):
        return views.library(st, view, key, "", "all", None, **kw)["rows"]

    assert side["all_tracks"] == len(rows("all")) and side["not_in_playlist"] == len(rows("unlisted"))
    assert [p["songs"] for p in side["playlists"]] == [len(rows("playlist", p["name"])) for p in side["playlists"]]
    assert [f["name"] for f in side["library_folders"]] == ["Extra", "Loose", "Technology"]
    assert [f["files"] for f in side["library_folders"]] == [1, 1, 1]  # `far` counts under Loose, `local:9` under Extra
    folders = [*side["library_folders"], *side["watched"], *(c for w in side["watched"] for c in w["crates"])]
    assert len(folders) > 6 and all(f["files"] == len(rows("folder", f["path"])) for f in folders)


def test_a_folder_that_holds_only_own_files_has_a_sidebar_row_and_a_file_outside_its_songs_folder_is_counted_where_it_sits():
    st = state(a=song("Techno", "One", "Library/Techno/Example Artist - One.aiff"),
               far=song("Techno", "Far", "Library/Loose/Example Artist - Far.aiff"),
               **{"local:1": mine("Library/Extra/not_lossless/Example Artist - Own.mp3", "not_lossless", cutoff=20000)})
    side = views.sidebar(st, [TECHNO], 0)
    assert side["library_folders"] == [{"path": "Library/Extra", "name": "Extra", "files": 1},
                                       {"path": "Library/Loose", "name": "Loose", "files": 1}]
    assert [r["track_id"] for r in views.library(st, "folder", "Library/Extra", "", "all", None, lines=[TECHNO])["rows"]] == [
        "local:1"]


def test_a_playlist_view_says_how_many_of_its_songs_have_a_file_whatever_the_search_and_filter():
    out = playlist_view()
    assert out["songs"] == {"listed": 5, "with_file": 3} and out["summary"]["tracks"] == 3  # a, b, c | g, unheard
    assert playlist_view(query="one", filt="lossless")["songs"] == out["songs"]
    assert playlist_view(records={})["songs"] is None  # never read
    assert views.library(playlist_state(), "all", None, "", "all", None, lines=[TECHNO])["songs"] is None
    assert views.library(playlist_state(), "playlist", "Nowhere", "", "all", None, lines=[TECHNO])["songs"] is None


def test_a_hidden_song_that_was_not_found_still_says_it_is_hidden_so_the_page_sends_nobody_to_the_to_do_list():
    st = state(**{**playlist_state()["tracks"], "g": {**playlist_state()["tracks"]["g"], "hidden": True}})
    rows = {r["track_id"]: r for r in playlist_view(st)["rows"]}
    assert (rows["g"]["wait"], rows["g"]["hidden"]) == ("not_found", True)
    assert {r["track_id"]: r["hidden"] for r in playlist_view()["rows"]}["g"] is False
    assert "not_found" not in [g["key"] for g in views.todo(st, "all", False, {}, TODAY)["groups"]]  # nothing to open


def test_the_also_rows_come_by_artist_then_title_and_the_playlists_own_rows_keep_their_order():
    st = state(**playlist_state()["tracks"],
               e1=song("Techno", "Zed", "Library/Techno/Example Artist - Zed.aiff"),
               e2=e(folder="Techno", artist="Abe", title="Mid", path="Library/Techno/Abe - Mid.aiff"),
               e3=song("Techno", "Aaa", "Library/Techno/Example Artist - Aaa.aiff"))
    for sort in (None, "order"):
        out = playlist_view(st, sort=sort)
        assert [r["track_id"] for r in out["also"]] == ["e2", "e3", "d", "e1"]  # Abe; Example Artist: Aaa, Four, Zed
        assert [r["track_id"] for r in out["rows"]][:3] == ["a", "b", "c"]
    assert [r["track_id"] for r in playlist_view(st, sort="-order")["also"]] == ["e1", "d", "e3", "e2"]


def _df(file_id, status="lossless", cutoff=None, path=None, in_playlists=False):
    return DupFile(file_id, None, path or f"/Volumes/Example/Music/x{file_id}.aiff", status, cutoff, None, True,
                   in_playlists)


@pytest.mark.parametrize("files,pick", [
    # the better sound wins: lossless before lossy, then the higher cutoff
    ([_df(1, "not_lossless", 20000), _df(2)], (2, views.RECOMMEND_QUALITY)),
    ([_df(1, "not_lossless", 16000), _df(2, "not_lossless", 20000), _df(3, "not_lossless", 17000)],
     (2, views.RECOMMEND_QUALITY)),
    # same sound: AIFF before another format (it keeps tags)
    ([_df(1, path="/Volumes/Example/Music/x.wav"), _df(2, path="Library/A/x.aiff")], (2, views.RECOMMEND_AIFF)),
    ([_df(1, path="/Volumes/Example/Music/x.aif"), _df(2, path="/Volumes/Example/Music/x.flac")],
     (1, views.RECOMMEND_AIFF)),
    # no clear winner: same sound and format; a playlist or Library/ breaks no tie
    ([_df(1, in_playlists=True), _df(2, path="Library/A/x.aiff")], (None, None)),
    ([_df(1, path="/a/x.wav"), _df(2, path="/b/x.flac")], (None, None)),
    ([_df(1), _df(2), _df(3, "not_lossless", 20000)], (None, None)),  # the two best tie
])
def test_recommend_picks_the_file_to_keep_or_none(files, pick):
    assert views.recommend(files) == pick


def test_a_duplicate_item_carries_the_recommendation():
    st = state(**{"local:1": own(file_id=4), "local:2": own("not_lossless", cutoff=16000, file_id=5)})
    g = DuplicateGroup("dup:4-5", "same_audio", (4, 5))
    files = {g.id: [dup_file(4, "local:1"), dup_file(5, "local:2", "not_lossless", 16000)]}
    pair = views.todo(st, "all", False, {}, TODAY, None, [], [g], files)["groups"][0]["items"][0]["pair"]
    assert (pair["recommended"], pair["recommended_why"]) == (4, "Recommended: best quality")
