from dataclasses import replace
from datetime import date, datetime

import pytest

from discjockey.hub import views
from discjockey.hub.jobs import PreviewStore
from discjockey.models import (Action, BatchResult, BatchRow, FetchedPlaylist, MoveRow, Plan, PlannedMove, PlaylistLine,
                               SpotifyTrack)
from discjockey.planner import ENTRY_KEYS, tidy_rows
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
    return SpotifyTrack(tid, f"Song {tid}", ("Artist",), "Al", None, 180000, None)


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


def test_still_to_load():
    money = {"remaining": 10, "limit": 60}
    store = store_with([a("acquire", f"t{i}", "new") for i in range(12)] + [a("upgrade", "u")])
    assert views.still_to_load(store.prep, money, state()) == {"count": 12, "days": 2, "fits_today": False}
    assert views.still_to_load(None, money, state()) == {"count": None, "days": None, "fits_today": None}
    never = state()
    never["never"] = {"t0": {}, "t1": {}, "t2": {}}
    assert views.still_to_load(store.prep, money, never) == {"count": 9, "days": 1, "fits_today": True}


def test_spotify_status():
    store = store_with([])
    st = views.spotify_status(store, NOW, reading=False)
    assert st["read_at"] == "2026-10-20T21:45:00" and st["minutes_ago"] == 2 and not st["offline"]
    store.failed("offline", "Cannot reach Spotify.")
    st = views.spotify_status(store, NOW, reading=True)
    assert st["offline"] and st["problem"] == "offline" and st["reading"] and st["read_at"] == "2026-10-20T21:45:00"


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
                   "source": "youtube", "source_name": "YouTube", "in_playlists": True, "hidden": False,
                   "upgrade_ready": True, "path": "Library/A/x.aiff", "added": None, "cover_url": "cover:t1"}


@pytest.mark.parametrize("alignment,text", [
    ({"result": "exact"}, "matches exactly, cues stay"),
    ({"result": "shifted", "offset_ms": -23.0}, "aligned by 23 ms, cues stay"),
    ({"result": "different"}, "doesn't match: would be a new rekordbox entry"),
    (None, "could not compare the two versions"),
])
def test_cue_text(alignment, text):
    assert views.cue_text(alignment) == text


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
    assert d["upgrade"] is None and d["spotify_url"] == "https://open.spotify.com/track/t1"


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
    lib = views.library(LIB, "Hard_Bounce", "", "all", "title")
    assert [r["title"] for r in lib["rows"]] == ["Balling (LÄUFF Remix)", "Get Naughty", "Gimme Gimme", "Old Favourite"]
    assert lib["chips"] == {"all": 4, "lossless": 2, "good_lossy": 1, "weak": 1, "fake": 0, "upgrade_ready": 1}
    assert lib["summary"] == {"tracks": 4, "lossless_share": 0.5, "upgrades_ready": 1, "to_do": 2,
                              "by_quality": {"lossless": 2, "good_lossy": 1, "weak": 1, "fake": 0, "missing": 0}}
    assert lib["empty"] is None
    assert [r["title"] for r in views.library(LIB, "Hard_Bounce", "", "weak", "title")["rows"]] == ["Get Naughty"]
    assert [r["title"] for r in views.library(LIB, "Hard_Bounce", "", "all", "-length")["rows"]][0] == "Get Naughty"


def test_library_summary_ignores_search_and_filter():
    """The panel's folder overview stays the folder's, whatever the table shows."""
    whole = views.library(LIB, "Hard_Bounce", "", "all", "artist")["summary"]
    assert views.library(LIB, "Hard_Bounce", "gimme", "weak", "artist")["summary"] == whole


def test_library_to_do_counts_only_what_the_to_do_list_shows():
    s = state(**{**LIB["tracks"], "h": e("not_lossless", folder="Hard_Bounce", cutoff=16000, hidden=True)})
    # b (upgrade) and c (good lossy) are to-dos; a is lossless, f is in no playlist, h is hidden
    assert views.library(s, "Hard_Bounce", "", "all", "artist")["summary"]["to_do"] == 2


def test_library_sorts_by_folder_with_unlisted_tracks_last():
    rows = views.library(LIB, None, "", "all", "folder")["rows"]
    assert [r["folder"] for r in rows] == ["Bouncy", "Hard_Bounce", "Hard_Bounce", "Hard_Bounce", "Hard_Bounce"]
    assert rows[-1]["track_id"] == "f"


def test_library_search_all_tracks_and_not_in_a_playlist():
    assert [r["track_id"] for r in views.library(LIB, None, "läuff", "all", "artist")["rows"]] == ["c"]
    assert views.library(LIB, None, "", "all", "artist")["summary"]["tracks"] == 5  # not found ones have no file
    nip = views.library(LIB, views.NOT_IN_PLAYLIST, "", "all", "artist")
    assert nip["title"] == "Not in a playlist" and [r["track_id"] for r in nip["rows"]] == ["f"]
    assert views.library(LIB, None, "nothing like this", "all", "artist")["empty"] == "no_match"
    assert views.library(state(), None, "", "all", "artist")["empty"] == "empty_library"


def test_sidebar():
    sb = views.sidebar(LIB, ["Hard_Bounce", "Powertrance"], 3)
    assert sb == {"todo": 3, "all_tracks": 5, "not_in_playlist": 1, "limits_warning": False,
                  "folders": [{"folder": "Hard_Bounce", "tracks": 4, "in_playlists_txt": True},
                              {"folder": "Powertrance", "tracks": 0, "in_playlists_txt": True},
                              {"folder": "Bouncy", "tracks": 1, "in_playlists_txt": False}]}


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
    assert by["b"]["detail"] == "aligned by 23 ms, cues stay" and by["b"]["group"] == "upgrade_ready"
    assert by["g"]["detail"] == "next try in 3 days" and by["n"]["detail"] == "tried again at the next sync"
    assert by["c"]["detail"] == "YT Music" and by["k"]["detail"] == "Qobuz"
    assert by["m"]["detail"] == "MOVE BLOCKED · a file is in the way"
    assert "h" not in by and "f" not in by and out["hidden_count"] == 1
    assert out["chips"] == {"all": 6, "rekordbox_check": 0, "upgrade_ready": 1, "not_found": 2, "weak": 0, "good_lossy": 1, "fake": 1,
                            "other": 1}
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
    store.ready(Prepared(None, st, Settings(), Plan(st, [], [(t("amb"), "A", ["Library/A/x.aiff"])], []), None),
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
    assert p["notes"] == ["a note"] and p["empty"] is None and p["spotify"]["minutes_ago"] == 2


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
    from discjockey.spotify import PlaylistInfo
    info = PlaylistInfo(ID1, "Hard Bounce 2026", "dj1", "DJ One", False, "big", 3, True)
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
    spotify_only = SpotifyTrack("n1", "Fresh", ("Newcomer",), "Al", "https://i.scdn.co/image/n1", 180000, None)
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
    assert by["a"]["detail"] == ("This track now plays the right song. In rekordbox: analyse it again and delete the "
                                 "old cues (they belong to the wrong song).")
    assert by["h"]["detail"] == "This is a different edit. In rekordbox: analyse it again and set the cues again."
    assert out["chips"]["rekordbox_check"] == 2 and out["chips"]["all"] == 2 and out["hidden_count"] == 1
    both = views.todo(s, "all", True, {}, TODAY)
    assert [g["key"] for g in both["groups"]] == ["rekordbox_check", "not_found"] and both["chips"]["all"] == 2


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
    ("place_taken", None, {"old": "Old", "new": "New"}, "A folder or another playlist called Old is there again."),
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


def test_undo_preview_of_a_folder_rename():
    b = batch(2, "rename", moved=1, about={"from": "Old", "to": "New"})
    inside = ["Library/New/a.aiff", "Library/New/not_lossless/b.aiff", "Library/Newer/c.aiff", "Library/Other/d.aiff"]
    p = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", label="New")], inside)
    assert p["title"] == "Renamed Old to New" and p["moving"] == 2 and not p["nothing_left"]
    assert p["warning"] == ["2 files go back to where they were. rekordbox may show them as missing again; Relocate "
                            "finds them by file name.",
                            "The folder goes back to its old name Old, with everything in it, and the playlist is "
                            "called Old again."]
    assert p["rows"] == [{"label": "New", "from": "New", "to": "Old", "skip": None}]
    gone = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", label="New",
                                     skip=("playlist_renamed", None))], inside)
    assert gone["nothing_left"] and gone["warning"] == []
    assert gone["rows"][0]["skip"] == {"reason": "playlist_renamed", "text": "The playlist isn't called New any more"}
    taken = views.undo_preview(b, [pm("folder", src="Library/New", dst="Library/Old", skip=("place_taken", None)),
                                   pm("folder", src="Library/New", dst="Library/Old", skip=("moved_on", None))])
    assert [r["skip"]["text"] for r in taken["rows"]] == [
        "A folder or another playlist called Old is there again.", "The folder New isn't there any more"]


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
