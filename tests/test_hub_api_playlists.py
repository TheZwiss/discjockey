import hashlib
import json
import shlex
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp
from hub_helpers import (ID1, ID2, PLAYLISTS, QOBUZ_ID, QOBUZ_LINK, QOBUZ_UNREADABLE, TRACKS, fake_qobuz, fake_spotify,
                         make_api, make_root, refreshed, store_sync_read, stored, track, wait_job, window)

from discjockey.config import ConfigError
from discjockey import db, playlist_words, sources, words
from discjockey import playlists_file as pf
from discjockey.hub import views
from discjockey.hub.api import CliApi, HubApi, PLAYLIST_COPIES
from discjockey.hub.history import GUARD
from discjockey.events import CancelToken
from discjockey.models import FetchedPlaylist, PlaylistInfo, PlaylistLine
from discjockey.sources.base import LoginState, SourceError
from discjockey.sources import soundcloud, spotify, youtube_music
from discjockey.hub.api import rows_from, suggest_folder
from discjockey.library import run_lock
from discjockey.settings import Account, Settings, save_settings

ID3 = "37i9dQZF1DXcBWIGoYBM5M"
LINK3 = f"https://open.spotify.com/playlist/{ID3}?si=x"


@pytest.fixture
def root(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, {**TRACKS, ID3: [track("t6", "New One", "Someone"), track("t1", "Gimme Gimme",
                                                                                         "Vatoz Locoz", 156000)]})
    return make_root(tmp_path)


def lines(*rows):
    return [{"folder": f, "link": link, "enabled": on} for f, link, on in rows]


HARD = ("Hard_Bounce", f"https://open.spotify.com/playlist/{ID1}", True)
POWER = ("Powertrance", f"https://open.spotify.com/playlist/{ID2}", True)


def test_playlists_page_after_a_refresh(root):
    api, rec = make_api(root)
    assert api.playlists()["rows"][0]["info"] is None
    refreshed(api, rec)
    page = api.playlists()
    assert [r["folder"] for r in page["rows"]] == ["Hard_Bounce", "Powertrance"]
    assert page["rows"][0]["info"]["name"] == f"Name of {ID1[:4]}" and page["rows"][0]["tracks"] == 4
    assert [o["track_id"] for o in page["overlaps"]] == ["t2"] and page["version"]


def test_a_playlist_switched_off_before_any_read_is_listed_with_a_quality_of_zeros_and_can_be_switched_on(root):
    # issue 38: nothing was read of the off line, so the row had `quality: null` and the page crashed on its switch
    api, rec = make_api(root)
    root.playlists_file.write_text(f"Hard_Bounce = https://open.spotify.com/playlist/{ID1}\n"
                                   f"#off# Powertrance = https://open.spotify.com/playlist/{ID2}\n")
    zeros = {"lossless": 0, "good_lossy": 0, "weak": 0, "fake": 0, "missing": 0}
    rows = api.playlists()["rows"]
    assert [(r["folder"], r["enabled"], r["quality"]) for r in rows] == [("Hard_Bounce", True, zeros),
                                                                       ("Powertrance", False, zeros)]
    on = api.preview_playlist_change(lines(HARD, POWER), read_unread=True)  # the switch back on, read once right here
    assert on["ok"] and on["kind"] == "add" and on["problem"] is None
    off = api.preview_playlist_change(lines(HARD, (POWER[0], POWER[1], False)), read_unread=True)
    assert off["kind"] == "none"  # unchanged from the file: switched off already


def test_add_a_playlist(root):
    api, rec = make_api(root)
    added = api.add_playlist(LINK3)
    assert added["ok"] and added["link"] == f"https://open.spotify.com/playlist/{ID3}" and added["tracks"] == 2
    assert added["readable"] and added["hint"] is None
    assert (added["playlist_id"], added["service"], added["service_name"]) == (ID3, "spotify", "Spotify")
    assert [list(m) for m in stored(root)] == [[ID3], [ID3]]  # a Spotify playlist keeps its bare id
    assert added["info"]["hint"] == "Follow ≠ own: make your own copy in Spotify."  # short enough for a row
    refused = api.add_playlist("https://open.spotify.com/album/x")
    assert refused["kind"] == "refused" and "service" not in refused


def test_a_pasted_playlist_is_still_known_to_a_new_window(root):
    """What an add read (the info and the tracks) was window memory before: now a window opened later still has it."""
    api, rec = make_api(root)
    assert api.add_playlist(LINK3)["ok"]
    api, rec = make_api(root)  # a new HubApi on the same music folder
    root.playlists_file.write_text(root.playlists_file.read_text() + f"Pasted = https://open.spotify.com/playlist/{ID3}\n")
    row = [r for r in api.playlists()["rows"] if r["folder"] == "Pasted"][0]
    assert row["info"]["name"] == f"Name of {ID3[:4]}" and row["tracks"] == 2


def test_the_preview_of_an_edited_line_stores_what_it_read_as_a_check_read(root):
    api, rec = make_api(root)
    change = api.preview_playlist_change(lines(HARD, ("New", LINK3, True)), read_unread=True)
    assert change["ok"]
    tracks, _ = stored(root)
    assert [t.id for t in tracks[ID3]] == ["t6", "t1"]
    with db.connect(root.db_file, read_only=True) as conn:
        assert [r[0] for r in conn.execute("SELECT kind FROM reads")] == ["check"] * 2  # one per playlist read
        assert db.load_read(conn) is None  # a check read is no sync read: the Sync plan has none yet


def test_a_followed_playlist_is_not_readable(root, monkeypatch):
    monkeypatch.setattr(spotify, "playlist_info", lambda s, pid, me: PlaylistInfo(
        "spotify", pid, "Their list", "someone", "Someone", False, None, 30, False, False))
    api, rec = make_api(root)
    added = api.add_playlist(LINK3)
    assert not added["readable"] and added["tracks"] is None and "Follow ≠ own" in added["hint"]


def test_add_a_qobuz_playlist(root, monkeypatch):
    fake_qobuz(monkeypatch)
    api, rec = make_api(root)
    added = api.add_playlist(f"https://play.qobuz.com/playlist/{QOBUZ_ID}")
    assert added["ok"] and added["link"] == QOBUZ_LINK and added["tracks"] == 1
    assert (added["playlist_id"], added["service"], added["service_name"]) == (f"qobuz:{QOBUZ_ID}", "qobuz", "Qobuz")
    assert added["readable"] and added["hint"] is None and added["suggested_folder"] == "Example_Playlist"
    assert added["info"]["owner_name"] == "Example Curator"
    assert added["info"]["hint"] == "Make it public in Qobuz, or use one of your own playlists."
    assert [list(m) for m in stored(root)] == [[f"qobuz:{QOBUZ_ID}"]] * 2


def test_a_qobuz_playlist_qobuz_wont_show_answers_with_its_service(root, monkeypatch):
    fake_qobuz(monkeypatch, unreadable=True)
    api, rec = make_api(root)
    assert window(api.add_playlist(QOBUZ_LINK)) == {"ok": False, "kind": "playlist_unreadable", "service": "qobuz",
                                            "message": QOBUZ_UNREADABLE}
    assert stored(root) == ({}, {})


@pytest.mark.parametrize("kind,message", [
    ("offline", "Qobuz is not responding (HTTP 503). Try again later."),
    ("qobuz_login_failed", "Could not log in to Qobuz: the password was refused.")])
def test_a_qobuz_that_will_not_open_answers_with_its_service(root, monkeypatch, kind, message):
    fake_qobuz(monkeypatch, open_error=SourceError(message, kind, "qobuz"))
    api, rec = make_api(root)
    assert window(api.add_playlist(QOBUZ_LINK)) == {"ok": False, "kind": kind, "service": "qobuz", "message": message}
    assert stored(root) == ({}, {})


def test_a_reader_that_fails_to_close_does_not_replace_the_answer(root, monkeypatch):
    fake_qobuz(monkeypatch, close_fails=True)
    api, rec = make_api(root)
    added = api.add_playlist(QOBUZ_LINK)
    assert added["ok"] and added["tracks"] == 1
    fake_qobuz(monkeypatch, unreadable=True, close_fails=True)
    assert api.add_playlist(QOBUZ_LINK)["kind"] == "playlist_unreadable"


@pytest.mark.parametrize("service,link", [("qobuz", QOBUZ_LINK), ("spotify", LINK3)])
def test_a_service_that_is_not_connected_is_named_when_adding(root, monkeypatch, service, link):
    fake_qobuz(monkeypatch, connected=False)
    monkeypatch.setattr(spotify, "login_state", lambda p: spotify.LoginState("missing", spotify.NOT_SET_UP))
    api, rec = make_api(root)
    name = service.capitalize()
    assert window(api.add_playlist(link)) == {"ok": False, "kind": "not_set_up", "service": service,
                                      "message": f"Connect {name} first."}


SC_SET = "https://soundcloud.com/example-label/sets/example-set"


def fake_soundcloud(monkeypatch, *, expand_error=None):
    """A service that is read without a login (login_state: not_needed), as SoundCloud will be: its source module
    stands in the registry, so the hub's handling of such a service is pinned before the real module exists."""
    calls = []

    class Reader:
        want_info = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

        def close(self):
            pass

        def info(self, playlist_id):
            return PlaylistInfo("soundcloud", playlist_id, "Example Set", "example-label", "Example Label", False,
                                None, 1, False, True)

        def fetch(self, line):
            return FetchedPlaylist(line, [track("900000101", "Example Title", "Example Artist")], [])

    def expand(link, paths, token):
        calls.append(link)
        if expand_error:
            raise expand_error
        if link.startswith("https://on.soundcloud.com/"):
            return SC_SET
        return link.replace("/you/likes", "/example-dj/likes")

    monkeypatch.setitem(sources.SOURCES, "soundcloud", SimpleNamespace(
        SERVICE="soundcloud", UNREADABLE_HINT="x",
        recognise=lambda link: link.split("https://soundcloud.com/", 1)[1] if link.startswith("https://soundcloud.com/")
        else None,
        canonical_link=lambda pid: f"https://soundcloud.com/{pid}", login_state=lambda paths: LoginState("not_needed"),
        open=lambda paths, token: Reader(), expand=expand))
    return calls


def test_a_service_that_needs_no_login_is_added_and_listed_connected(root, monkeypatch):
    calls = fake_soundcloud(monkeypatch)
    root.playlists_file.write_text(PLAYLISTS + f"Example_Set = {SC_SET}\n")
    api, rec = make_api(root)
    added = api.add_playlist(SC_SET)
    assert added["ok"] and added["tracks"] == 1 and added["readable"] and calls == [SC_SET]
    assert (added["playlist_id"], added["service"], added["service_name"]) == (
        "soundcloud:example-label/sets/example-set", "soundcloud", "SoundCloud")
    assert [(s["service"], s["connected"]) for s in api.job_status()["read_status"]["services"]] == [
        ("spotify", True), ("soundcloud", True)]


def test_add_playlist_adds_what_expand_made_of_the_link(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    added = make_api(root)[0].add_playlist("https://soundcloud.com/you/likes")
    assert added["ok"] and added["link"] == "https://soundcloud.com/example-dj/likes"
    assert added["playlist_id"] == "soundcloud:example-dj/likes"


def test_a_short_link_pasted_in_the_hub_reaches_expand_and_is_saved_as_the_full_link(root, monkeypatch):
    calls = fake_soundcloud(monkeypatch)  # recognise knows no short link, as the real SoundCloud source's
    short = "https://on.soundcloud.com/abc123"
    added = make_api(root)[0].add_playlist(f"  {short}  ")
    assert calls == [short] and added["ok"] and added["link"] == SC_SET
    assert added["playlist_id"] == "soundcloud:example-label/sets/example-set"


def test_a_short_link_in_playlists_txt_is_still_refused(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    short = "https://on.soundcloud.com/abc123"
    with pytest.raises(ValueError) as e:
        pf.clean_link(short)
    assert str(e.value).startswith("That isn't a playlist link Discjockey can read. Open the playlist in Spotify")
    root.playlists_file.write_text(PLAYLISTS + f"Short = {short}\n")
    assert "Short" not in [r.folder for r in pf.load(root.playlists_file).rows]


def test_an_expand_that_fails_answers_with_its_kind_and_service(root, monkeypatch):
    fake_soundcloud(monkeypatch, expand_error=SourceError("Use your profile's likes link.", "playlist_unreadable",
                                                          "soundcloud"))
    api, rec = make_api(root)
    assert window(api.add_playlist("https://soundcloud.com/you/likes")) == {
        "ok": False, "kind": "playlist_unreadable", "service": "soundcloud", "message": "Use your profile's likes link."}
    assert stored(root) == ({}, {})


def test_other_links_pass_expand_untouched(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    assert sources.expand(LINK3, root.support, CancelToken()) == LINK3  # Spotify defines no expand


def test_preview_reads_an_unread_playlist_of_a_service_that_needs_no_login(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    api, rec = make_api(root)
    refreshed(api, rec)
    added = api.preview_playlist_change(lines(HARD, POWER, ("Example_Set", SC_SET, True)), read_unread=True)
    assert added["ok"] and added["kind"] == "add" and added["new_downloads"] == 1


def test_a_preview_read_is_stamped_when_it_started_so_a_sync_read_that_started_during_it_keeps_its_record(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    reader = sources.SOURCES["soundcloud"].open(root.support, CancelToken())
    set_id = "example-label/sets/example-set"

    def slow_fetch(line):  # a sync read starts and stores its record while this check read is still fetching
        store_sync_read(root, [FetchedPlaylist(PlaylistLine("Example_Set", set_id, 3, "soundcloud"),
                                               [track("900000202", "From The Sync", "Example Artist")], [])])
        return FetchedPlaylist(line, [track("900000101", "From The Check", "Example Artist")], [])

    monkeypatch.setattr(reader, "fetch", slow_fetch)
    monkeypatch.setattr(sources.SOURCES["soundcloud"], "open", lambda paths, token: reader)
    api, rec = make_api(root)
    refreshed(api, rec)
    assert api.preview_playlist_change(lines(HARD, POWER, ("Example_Set", SC_SET, True)), read_unread=True)["ok"]
    tracks, _ = stored(root)
    assert [t.title for t in tracks[f"soundcloud:{set_id}"]] == ["From The Sync"]


def test_preview_does_not_open_soundcloud_for_a_you_likes_line(root, monkeypatch):
    """Reading your own likes opens the browser login (a Keychain prompt): a preview skips such a line."""
    fake_soundcloud(monkeypatch)

    reader = sources.SOURCES["soundcloud"].open(root.support, CancelToken())

    def read(line):
        raise AssertionError("the preview read your likes")
    monkeypatch.setattr(reader, "fetch", read)
    monkeypatch.setattr(sources.SOURCES["soundcloud"], "open", lambda paths, token: reader)
    monkeypatch.setattr(sources.SOURCES["soundcloud"], "recognise", lambda link: "you/likes")
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(HARD, POWER, ("Likes", "https://soundcloud.com/you/likes", True)), read_unread=True)
    assert c["ok"]


def test_the_page_lists_a_qobuz_row_by_its_ref(root, monkeypatch):
    fake_qobuz(monkeypatch)
    root.playlists_file.write_text(PLAYLISTS + f"Example_Playlist = {QOBUZ_LINK}\n")
    api, rec = make_api(root)
    refreshed(api, rec)
    rows = api.playlists()["rows"]
    assert [(r["playlist_id"], r["service"], r["service_name"]) for r in rows] == [
        (ID1, "spotify", "Spotify"), (ID2, "spotify", "Spotify"), (f"qobuz:{QOBUZ_ID}", "qobuz", "Qobuz")]
    assert rows[2]["info"]["name"] == "Example Playlist" and rows[2]["tracks"] == 1
    assert rows[2]["info"]["hint"] == "Make it public in Qobuz, or use one of your own playlists."


def test_preview_reads_an_unread_qobuz_playlist_and_skips_one_that_fails(root, monkeypatch):
    fake_qobuz(monkeypatch)
    api, rec = make_api(root)
    refreshed(api, rec)
    added = api.preview_playlist_change(lines(HARD, POWER, ("Q", QOBUZ_LINK, True)), read_unread=True)
    assert added["ok"] and added["kind"] == "add" and added["new_downloads"] == 1
    fake_qobuz(monkeypatch, unreadable=True)
    other = api.preview_playlist_change(lines(HARD, POWER, ("Q2", "https://open.qobuz.com/playlist/900000002", True)), read_unread=True)
    assert other["ok"] and other["kind"] == "unknown"  # nothing read for it: the page can't say what it adds
    fake_qobuz(monkeypatch, connected=False)  # not connected: no read either, and no failure
    none = api.preview_playlist_change(lines(HARD, ("Q3", "https://open.qobuz.com/playlist/900000003", True)), read_unread=True)
    assert none["ok"] and none["kind"] == "unknown"


def test_preview_skips_a_service_that_will_not_open_and_reads_the_others(root, monkeypatch):
    fake_qobuz(monkeypatch, open_error=SourceError("Qobuz is not responding (HTTP 503). Try again later.", "offline",
                                                   "qobuz"))
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(HARD, ("New", LINK3, True), ("Q", QOBUZ_LINK, True)), read_unread=True)
    assert c["ok"] and c["kind"] == "add" and c["new_downloads"] == 1  # Spotify's new playlist was read
    assert f"qobuz:{QOBUZ_ID}" not in stored(root)[0]


def test_preview_of_a_reorder_and_of_an_added_playlist(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(POWER, HARD), read_unread=True)
    assert c["ok"] and c["kind"] == "moves" and [m["track_id"] for m in c["tidy"]["rows"]] == ["t2"]
    assert c["tidy"]["rows"][0]["to"].endswith("/not_lossless") and c["problem"] is None
    added = api.preview_playlist_change(lines(HARD, POWER, ("New", LINK3, True)), read_unread=True)  # read once, right here
    assert added["kind"] == "add" and added["new_downloads"] == 1


def test_preview_says_what_is_wrong_with_the_lines(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(HARD, ("hard_bounce", LINK3, True)), read_unread=True)
    assert c["ok"] and "already used" in c["problem"]


def test_save_keeps_comments_and_writes_off_lines(root):
    api, rec = make_api(root)
    page = api.playlists()
    f = wait_job(api, rec, api.save_playlists(lines(POWER, (HARD[0], HARD[1], False)), page["version"]))
    assert f.ok and f.kind == "save_playlists"
    assert root.playlists_file.read_text() == (f"# my playlists\nPowertrance = https://open.spotify.com/playlist/{ID2}\n"
                                               f"#off# Hard_Bounce = https://open.spotify.com/playlist/{ID1}\n")
    assert f.result["version"] == api.playlists()["version"]


def test_save_refuses_a_file_changed_elsewhere(root):
    api, rec = make_api(root)
    version = api.playlists()["version"]
    root.playlists_file.write_text(PLAYLISTS + "# edited by hand\n")
    f = wait_job(api, rec, api.save_playlists(lines(POWER, HARD), version))
    assert (f.ok, f.problem) == (False, "changed") and "changed elsewhere" in f.message


def test_save_refuses_invalid_rows_and_waits_for_the_console(root):
    api, rec = make_api(root)
    version = api.playlists()["version"]
    f = wait_job(api, rec, api.save_playlists(lines(("not_lossless", HARD[1], True)), version))
    assert (f.ok, f.problem) == (False, "refused") and "reserved" in f.message
    assert api.save_playlists([{"folder": "x"}], version)["kind"] == "refused"
    with run_lock(root.lock):
        assert api.save_playlists(lines(HARD), version)["kind"] == "console"
    assert root.playlists_file.read_text() == PLAYLISTS


def test_saving_a_changed_list_marks_the_plan_as_from_the_old_lines_until_the_next_read(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    assert api.sync_preview()["read_status"]["lines_changed"] is False
    wait_job(api, rec, api.save_playlists(lines(POWER, HARD), api.playlists()["version"]))
    assert api.sync_preview()["read_status"]["lines_changed"] is True
    assert make_api(root)[0].job_status()["read_status"]["lines_changed"] is True  # any window: it is derived
    refreshed(api, rec)
    assert api.sync_preview()["read_status"]["lines_changed"] is False


def test_a_comment_line_does_not_change_the_lines(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    root.playlists_file.write_text("# a new comment shifts every line number\n" + root.playlists_file.read_text())
    assert api.sync_preview()["read_status"]["lines_changed"] is False


@pytest.mark.parametrize("name,folder", [("Hard Bounce 2026", "Hard_Bounce_2026"), ("POWERTRANCE 🔥", "POWERTRANCE"),
                                         ("a/b: c", "ab_c"), ("", "New_playlist"), ("not_lossless", "New_playlist")])
def test_suggest_folder(name, folder):
    assert suggest_folder(name) == folder


def test_rows_from_checks_the_links():
    with pytest.raises(ValueError) as e:
        rows_from([{"folder": "A", "link": "https://example.com"}])
    assert str(e.value) == ("This is not a playlist link Discjockey can read (Spotify, Qobuz, SoundCloud or YouTube "
                            "Music): https://example.com")


# --- SoundCloud and YouTube Music through the real source modules (plan library stage 6, group 5) ---

W9 = ("SoundCloud didn't accept the login from Chrome. Log in to SoundCloud there, or use your profile's likes link "
      "(soundcloud.com/your-name/likes).")
W17 = ("Discjockey can't read your liked videos or Watch later. Add the songs to a playlist, set it to public or "
       "unlisted, and paste that link.")
W18 = "This is a YouTube mix, which changes every time it plays. Save its songs to a playlist and paste that link."
YTM_FIXTURE = Path(__file__).parent / "fixtures" / "youtube_music" / "video_playlist.json"
YTM_ID = "PLexampleVideoList000000000000000001"
YTM_LINK = f"https://music.youtube.com/playlist?list={YTM_ID}"


class OneAnswerYDL:
    """A yt-dlp that answers the one YouTube Music playlist page with the recorded flat playlist (made-up ids)."""

    requested: list = []

    def __init__(self, opts):
        pass

    def extract_info(self, url, download=True, process=True, **kwargs):
        OneAnswerYDL.requested.append(url)
        return json.loads(YTM_FIXTURE.read_text())

    def close(self):
        pass


def test_pasting_a_youtube_music_link_reads_the_page_once(root, monkeypatch):
    OneAnswerYDL.requested = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", OneAnswerYDL)
    api, rec = make_api(root)
    assert api.add_playlist(YTM_LINK)["ok"]
    assert OneAnswerYDL.requested == [YTM_LINK]  # not once for info() and again for fetch()


def test_a_youtube_music_link_is_added_with_its_service_and_ref(root, monkeypatch):
    OneAnswerYDL.requested = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", OneAnswerYDL)
    api, rec = make_api(root)
    added = api.add_playlist(f"  https://www.youtube.com/watch?v=EXAMPLEid01&list={YTM_ID}&si=x ")
    entries = json.loads(YTM_FIXTURE.read_text())["entries"]
    assert added["ok"] and added["readable"] and 0 < added["tracks"] <= len(entries)
    assert (added["playlist_id"], added["service"], added["service_name"]) == (
        f"youtube_music:{YTM_ID}", "youtube_music", "YouTube Music")
    assert added["link"] == YTM_LINK and added["hint"] is None
    assert added["info"]["hint"] == youtube_music.UNREADABLE_HINT
    assert stored(root)[1][f"youtube_music:{YTM_ID}"].service == "youtube_music"


@pytest.mark.parametrize("pid, words", [("LL", W17), ("WL", W17), ("RDEXAMPLEmix0001", W18)])
def test_a_youtube_music_list_that_is_refused_answers_with_its_service(root, monkeypatch, pid, words):
    OneAnswerYDL.requested = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", OneAnswerYDL)
    api, rec = make_api(root)
    assert window(api.add_playlist(f"https://music.youtube.com/playlist?list={pid}")) == {
        "ok": False, "kind": "playlist_unreadable", "service": "youtube_music", "message": words}
    assert OneAnswerYDL.requested == [] and stored(root) == ({}, {})  # refused before any request


def test_your_own_likes_without_a_soundcloud_login_answer_w8(root, monkeypatch):
    api, rec = make_api(root)  # no SoundCloud account in the support folder: expand asks for none and says so
    answer = api.add_playlist("https://soundcloud.com/you/likes")
    assert window(answer) == {"ok": False, "kind": "playlist_unreadable", "service": "soundcloud", "message": soundcloud.LIKES_HINT}
    assert answer["message"].startswith("To read your own likes, use your profile's likes link")


def test_pasting_a_soundcloud_link_asks_the_service_once(root, monkeypatch):
    calls = []

    class Reader:
        want_info = False

        def close(self):
            pass

        def info(self, playlist_id):
            calls.append("info")
            raise AssertionError("the paste reads once")

        def fetch(self, line):
            calls.append("fetch")
            info = PlaylistInfo("soundcloud", line.playlist_id, "Example Set", "example-label", "Example Label", False,
                                None, 1, False, True) if self.want_info else None
            return FetchedPlaylist(line, [track("900000101", "Example Title", "Example Artist")], [], info)

    monkeypatch.setattr(soundcloud, "open", lambda paths, token: Reader())
    api, rec = make_api(root)
    added = api.add_playlist(SC_SET)
    assert added["ok"] and added["tracks"] == 1 and added["info"]["name"] == "Example Set"
    tracks, infos = stored(root)
    assert calls == ["fetch"] and infos["soundcloud:example-label/sets/example-set"].name == "Example Set"
    assert tracks["soundcloud:example-label/sets/example-set"][0].id == "900000101"


def test_a_soundcloud_set_that_is_not_shown_answers_w5(root, monkeypatch):
    class Reader:
        want_info = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def close(self):
            pass

        def info(self, playlist_id):
            raise SourceError(soundcloud.UNREADABLE_SET, "playlist_unreadable", "soundcloud")

        def fetch(self, line):  # worded for playlists.txt: the pasted link gets the page's own words from info()
            raise SourceError("playlists.txt line 1 (x): SoundCloud doesn't show this playlist.", "playlist_unreadable",
                              "soundcloud")

    monkeypatch.setattr(soundcloud, "open", lambda paths, token: Reader())
    api, rec = make_api(root)
    assert window(api.add_playlist(SC_SET)) == {"ok": False, "kind": "playlist_unreadable", "service": "soundcloud",
                                        "message": "SoundCloud doesn't show this playlist. It may be private or "
                                                   "removed; for a private set, use its private share link."}


@pytest.mark.parametrize("kind, message", [
    ("login_expired", W9), ("offline", "SoundCloud is not responding (URLError). Try again later."),
    ("offline", "SoundCloud asked Discjockey to slow down. Try again in an hour.")])
def test_a_soundcloud_login_or_network_problem_in_expand_never_rejects(root, monkeypatch, kind, message):
    def expand(link, paths, token):
        raise SourceError(message, kind, "soundcloud")

    monkeypatch.setattr(soundcloud, "expand", expand)
    api, rec = make_api(root)
    assert window(api.add_playlist("https://soundcloud.com/you/likes")) == {"ok": False, "kind": kind,
                                                                    "service": "soundcloud", "message": message}


def test_a_you_likes_line_whose_login_is_not_accepted_blocks_the_read_with_w9(root, monkeypatch):
    class Reader:
        want_info = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def close(self):
            pass

        def fetch(self, line):
            raise SourceError(W9, "login_expired", "soundcloud")

    monkeypatch.setattr(soundcloud, "open", lambda paths, token: Reader())
    root.playlists_file.write_text(PLAYLISTS + "Likes = https://soundcloud.com/you/likes\n")
    api, rec = make_api(root)
    done = wait_job(api, rec, api.refresh())
    assert not done.ok and (done.problem, done.service, done.message) == ("login_expired", "soundcloud", W9)
    status = api.job_status()["read_status"]
    assert (status["problem"], status["problem_service"], status["message"]) == ("login_expired", "soundcloud", W9)


# --- one change to the list by `op`, previewed and saved (issue 39 V4.2a) ---

NEW = ("Fresh", LINK3, True)
SHORT = "https://on.soundcloud.com/AbCdEf"


def snapshot(*roots):
    """The sha of every file under the folders: nothing may be written, not even to library.db."""
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for r in roots for p in sorted(Path(r).rglob("*"))
            if p.is_file()}


def oplog(root):
    return [json.loads(line) for line in root.operations_log.read_text().splitlines()] if root.operations_log.exists() else []


def newest(api):
    return api.history()["entries"][0]


def copies(root):
    return sorted(root.playlist_copies.glob("*.txt")) if root.playlist_copies.exists() else []


def count_fetches(monkeypatch):
    fetched = []
    real = spotify.fetch_playlist
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: (fetched.append(line.playlist_id), real(s, line))[1])
    return fetched


def test_the_playlists_page_numbers_its_rows_from_one(root):
    api, _ = make_api(root)
    assert [r["place"] for r in api.playlists()["rows"]] == [1, 2]


def test_a_preview_with_a_change_ends_with_the_line_that_makes_it_guarded_by_the_version_it_read(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    version = api.playlists()["version"]
    disabled = api.preview_playlist_change(op={"op": "disable", "playlist": "powertrance"})
    assert disabled["tidy"] is None
    assert disabled["next"] == [{"run": f"playlist disable powertrance --if-version {version}", "why": words.APPLY_WHY}]
    moved = api.preview_playlist_change(op={"op": "move", "playlist": "Powertrance", "to": 1})
    assert moved["tidy"] is not None  # files would move: one line for each answer to the question
    base = f"playlist move Powertrance --to 1 --if-version {version}"
    assert moved["next"] == [{"run": f"{base} --files move", "why": words.APPLY_MOVE_WHY},
                             {"run": f"{base} --files leave", "why": words.APPLY_LEAVE_WHY}]
    assert "next" not in api.preview_playlist_change(lines(POWER, HARD))  # the window's: no op, no line
    assert "next" not in api.preview_playlist_change()
    edited = api.preview_playlist_change(lines(POWER, HARD), op={"op": "disable", "playlist": "Powertrance"})
    assert "next" not in edited  # a change made to edited lines is not a change of the file: nothing to offer


def test_a_preview_whose_save_would_be_refused_offers_no_line(root, monkeypatch):
    api, rec = make_api(root)
    refreshed(api, rec)
    def refuse(rows):
        raise ConfigError("not a list a save would write")
    monkeypatch.setattr(pf, "validate", refuse)
    answer = api.preview_playlist_change(op={"op": "remove", "playlist": "Hard_Bounce"})
    assert answer["problem"] is not None and "next" not in answer


def test_the_line_that_makes_a_change_has_no_guard_for_no_file():
    op = {"op": "remove", "playlist": "Powertrance"}
    assert HubApi._apply_next(op, "", None) == [{"run": "playlist remove Powertrance", "why": words.APPLY_WHY}]
    [guarded] = HubApi._apply_next({"op": "add", "url": "https://a/b c", "folder": "X", "at": 2, "off": True}, "ab12", None)
    assert guarded["run"] == "playlist add 'https://a/b c' --folder X --at 2 --off --if-version ab12"


def test_a_preview_with_a_change_answers_the_lines_after_it_and_the_files_version(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    version = api.playlists()["version"]
    renamed = api.preview_playlist_change(op={"op": "rename", "playlist": "hard_bounce", "folder": "Hard_New"})
    assert renamed["ok"] and renamed["version"] == version and renamed["kind"] == "rename"
    assert [(r["folder"], r["enabled"]) for r in renamed["lines"]] == [("Hard_New", True), ("Powertrance", True)]
    assert renamed["lines"][0]["link"] == HARD[1]
    added = api.preview_playlist_change(op={"op": "add", "url": LINK3, "folder": "Fresh", "at": 1, "off": True})
    assert [(r["folder"], r["enabled"]) for r in added["lines"]] == [("Fresh", False), ("Hard_Bounce", True),
                                                                      ("Powertrance", True)]
    assert added["lines"][0]["link"] == f"https://open.spotify.com/playlist/{ID3}"  # the clean link
    assert root.playlists_file.read_text() == PLAYLISTS  # nothing was written
    swapped = api.preview_playlist_change(op={"op": "move", "playlist": "Powertrance", "to": 1})
    assert swapped["kind"] == "moves" and swapped["tidy"]["rows"]
    assert api.preview_playlist_change()["lines"] == lines_of(api)  # no lines, no op: the file as it is


def lines_of(api):
    return [{"folder": r["folder"], "link": r["link"], "enabled": r["enabled"]} for r in api.playlists()["rows"]]


def test_a_preview_with_lines_and_a_change_applies_the_change_to_those_lines(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    answer = api.preview_playlist_change(lines(POWER, HARD), {"op": "remove", "playlist": "powertrance"})
    assert [r["folder"] for r in answer["lines"]] == ["Hard_Bounce"]


def test_the_preview_keeps_to_the_network_and_the_disk_unless_the_window_asks(root, monkeypatch):
    api, rec = make_api(root)
    refreshed(api, rec)
    fetched = count_fetches(monkeypatch)
    before = snapshot(root.root, root.support)
    answer = api.preview_playlist_change(lines(HARD, POWER, NEW))
    assert answer["ok"] and fetched == [] and snapshot(root.root, root.support) == before
    assert answer["kind"] == "unknown" and answer["unknown"] == [ID3]
    assert answer["next"] == [{"run": shlex.join(["playlist", "check", LINK3]), "why": playlist_words.PLAYLIST_CHECK_COUNT_WHY}]
    answer = api.preview_playlist_change(lines(HARD, POWER, NEW), read_unread=True)  # the window's way reads it once
    assert fetched == [ID3] and answer["kind"] == "add" and "next" not in answer
    assert ID3 in stored(root)[0]


def test_a_preview_by_a_change_reads_nothing_either(root, monkeypatch):
    api, rec = make_api(root)
    refreshed(api, rec)
    fetched = count_fetches(monkeypatch)
    before = snapshot(root.root, root.support)
    answer = api.preview_playlist_change(op={"op": "add", "url": LINK3, "folder": "Fresh"})
    assert answer["kind"] == "unknown" and fetched == [] and snapshot(root.root, root.support) == before
    version = api.playlists()["version"]
    assert [n["run"] for n in answer["next"]] == [  # the check first, then the line that makes the change
        f"playlist check https://open.spotify.com/playlist/{ID3}",
        f"playlist add '{LINK3}' --folder Fresh --if-version {version}"]


def test_a_preview_without_a_read_runs_next_to_a_sync_and_the_windows_read_does_not(root, monkeypatch):
    api, rec = make_api(root)
    monkeypatch.setattr(api._jobs, "sync_running", lambda: True)
    assert api.preview_playlist_change(lines(HARD, POWER))["ok"]  # nothing to pace
    assert api.preview_playlist_change(lines(HARD, POWER), None, True)["kind"] == "sync_running"


def test_the_preview_of_files_that_move_carries_the_notes_the_tidy_up_does(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    tidy = api.preview_playlist_change(lines(POWER, HARD))["tidy"]
    assert (tidy["rekordbox"], tidy["undo_note"]) == (views.REKORDBOX_NOTES, views.UNDO_NOTE)


def test_an_add_without_a_folder_takes_the_suggestion_of_the_playlists_stored_read(root):
    api, rec = make_api(root)
    assert api.add_playlist(LINK3)["ok"]  # the check read stores its info
    answer = api.preview_playlist_change(op={"op": "add", "url": LINK3})
    assert answer["ok"] and answer["lines"][-1]["folder"] == f"Name_of_{ID3[:4]}"
    f = wait_job(api, rec, api.save_playlists(op={"op": "add", "url": LINK3}))
    assert f.ok and f"Name_of_{ID3[:4]} = https://open.spotify.com/playlist/{ID3}\n" in root.playlists_file.read_text()


def test_an_add_without_a_folder_of_a_playlist_nobody_read_says_to_check_it_first(root, monkeypatch):
    api, rec = make_api(root)
    fetched = count_fetches(monkeypatch)
    answer = api.preview_playlist_change(op={"op": "add", "url": LINK3})
    assert (answer["ok"], answer["kind"], answer["reason"], answer["message"]) == (
        False, "bad_args", "usage", playlist_words.PLAYLIST_ADD_NEEDS_FOLDER)
    assert answer["next"] == [{"run": shlex.join(["playlist", "check", LINK3]), "why": playlist_words.PLAYLIST_CHECK_NAME_WHY}]
    assert fetched == []
    assert api.save_playlists(op={"op": "add", "url": LINK3})["reason"] == "usage"  # the save says the same, no job


def test_an_add_of_a_listed_playlist_says_so_before_it_asks_for_a_folder(root):
    api, _ = make_api(root)
    answer = api.preview_playlist_change(op={"op": "add", "url": f"{HARD[1]}?si=zzz"})
    assert (answer["ok"], answer["kind"], answer["message"]) == (False, "refused", playlist_words.PLAYLIST_LISTED)
    assert api.save_playlists(op={"op": "add", "url": HARD[1], "folder": "Other"})["message"] == playlist_words.PLAYLIST_LISTED


def test_a_short_link_names_no_playlist_until_it_is_opened_so_a_change_does_not_open_it(root, monkeypatch):
    api, _ = make_api(root)
    opened = []
    monkeypatch.setattr(sources, "expand", lambda *a: opened.append(a) or a[0])
    for call in (api.preview_playlist_change, api.save_playlists):
        answer = call(op={"op": "add", "url": SHORT, "folder": "Warm"})
        assert (answer["kind"], answer["reason"], answer["message"]) == ("bad_args", "usage", playlist_words.PLAYLIST_ADD_LINK)
        assert answer["next"] == [{"run": f"playlist check {SHORT}", "why": playlist_words.PLAYLIST_CHECK_LINK_WHY}]
    assert opened == []


def test_the_liked_music_link_is_refused_while_its_choice_is_off(root):
    api, _ = make_api(root)
    answer = api.preview_playlist_change(op={"op": "add", "url": youtube_music.canonical_link("LM"), "folder": "Liked"})
    assert (answer["kind"], answer["message"]) == ("setting_off", youtube_music.SETTING_OFF)
    assert api.save_playlists(op={"op": "add", "url": youtube_music.canonical_link("LM"), "folder": "Liked"})["kind"] == "setting_off"


def test_a_change_that_cannot_be_made_is_refused_before_a_job_starts(root):
    api, _ = make_api(root)
    for op, said in (({"op": "remove", "playlist": "Nothing"}, "None of your playlists is called Nothing."),
                     ({"op": "move", "playlist": "Powertrance", "to": 3}, "A place in your playlists goes from 1 to 2."),
                     ({"op": "rename", "playlist": "Powertrance", "folder": "hard_bounce"},
                      "Another playlist already uses the folder Hard_Bounce."),
                     ({"op": "boil"}, "Discjockey can't make the change boil to your playlists."),
                     ("remove", "A playlist change needs op.")):
        for call in (api.preview_playlist_change, api.save_playlists):
            answer = call(op=op)
            assert (answer["ok"], answer["kind"], answer["message"]) == (False, "refused", said), (op, call)
    assert api._jobs.current is None


def test_a_save_takes_the_rows_or_one_change_not_both_and_not_none(root):
    api, _ = make_api(root)
    both = api.save_playlists(lines(HARD), None, None, {"op": "remove", "playlist": "Powertrance"})
    assert (both["kind"], both["message"]) == ("refused", playlist_words.SAVE_LINES_OR_OP)
    none = api.save_playlists()
    assert (none["kind"], none["message"]) == ("refused", playlist_words.SAVE_NOTHING)
    assert root.playlists_file.read_text() == PLAYLISTS and api._jobs.current is None


# (the change, the file after it, the logged name, the message)
SAVED_CHANGES = [
    ({"op": "add", "url": LINK3, "folder": "Fresh"}, "Fresh = https://open.spotify.com/playlist/" + ID3, "playlist_add",
     "Added the playlist Fresh at place 3."),
    ({"op": "add", "url": LINK3, "folder": "Fresh", "at": 1, "off": True}, "#off# Fresh = https://open.spotify.com/playlist/" + ID3,
     "playlist_add", "Added the playlist Fresh at place 1, switched off."),
    ({"op": "remove", "playlist": "Powertrance"}, None, "playlist_remove",
     "Removed the playlist Powertrance. Its files stay in your library."),
    ({"op": "rename", "playlist": "Powertrance", "folder": "Power"}, "Power = https://open.spotify.com/playlist/" + ID2,
     "playlist_rename", "Renamed the playlist Powertrance to Power."),
    ({"op": "move", "playlist": "Hard_Bounce", "to": 2}, None, "playlist_move",
     "Moved the playlist Hard_Bounce from place 1 to place 2."),
    ({"op": "disable", "playlist": "Powertrance"}, "#off# Powertrance = ", "playlist_disable",
     "Switched the playlist Powertrance off. Its files stay."),
]


@pytest.mark.parametrize("op, line, operation, message", SAVED_CHANGES)
def test_a_saved_change_is_logged_with_its_undo_and_history_offers_it(tmp_path, monkeypatch, op, line, operation, message):
    fake_spotify(monkeypatch, {**TRACKS, ID3: []})
    root = make_root(tmp_path)
    api, rec = make_api(root, api_class=CliApi)
    api.add_playlist(LINK3)  # so the folder of an add is not asked for... and the link is read
    before = root.playlists_file.read_text()
    version = api.playlists()["version"]
    f = wait_job(api, rec, api.save_playlists(op=op, loaded_version=version))
    assert f.ok and f.result == {"version": api.playlists()["version"], "batches": []}, f
    after = root.playlists_file.read_text()
    assert after != before and (line is None or line in after)
    [logged] = oplog(root)
    assert logged["operation"] == operation and logged["message"] == message and logged["result"] == "done"
    assert (logged["group"], logged["track_id"], logged["version"]) == ("playlists", "", f.result["version"])
    entry = newest(api)
    assert entry["text"] == message and entry["cant_text"] is None
    assert entry["undo"] == shlex.join([*logged["undo"], GUARD["playlists"], f.result["version"]])  # the built command, guarded
    assert copies(root) == []  # no copy: the undo is a change, not the file back


def test_a_change_made_on_a_stale_version_is_refused_with_the_command_that_lists_the_playlists(root):
    api, rec = make_api(root)
    stale = api.playlists()["version"]
    root.playlists_file.write_text(PLAYLISTS + "# edited by hand\n")
    f = wait_job(api, rec, api.save_playlists(op={"op": "remove", "playlist": "Powertrance"}, loaded_version=stale))
    assert (f.ok, f.problem, f.message) == (False, "changed", playlist_words.PLAYLISTS_VERSION_CHANGED)
    envelope = api._jobs.registry.get(f.job_id).result()
    assert (envelope["outcome"], envelope["reason"]) == ("refused", "version_changed")
    assert envelope["next"] == [{"run": "playlist list", "why": playlist_words.PLAYLISTS_LIST_WHY}]
    assert root.playlists_file.read_text() == PLAYLISTS + "# edited by hand\n" and oplog(root) == [] and copies(root) == []


def test_a_change_with_no_version_is_made_on_the_file_as_it_is(root):
    api, rec = make_api(root)
    root.playlists_file.write_text(PLAYLISTS + "# edited by hand\n")
    f = wait_job(api, rec, api.save_playlists(op={"op": "remove", "playlist": "Powertrance"}, loaded_version=None))
    assert f.ok and "Powertrance" not in root.playlists_file.read_text()
    assert "# edited by hand" in root.playlists_file.read_text()  # comments stay


def test_the_windows_save_with_a_stale_version_keeps_its_own_words(root):
    api, rec = make_api(root)
    stale = api.playlists()["version"]
    root.playlists_file.write_text(PLAYLISTS + "# edited by hand\n")
    f = wait_job(api, rec, api.save_playlists(lines(HARD), stale))
    assert (f.problem, f.message) == ("changed", pf.CHANGED_ELSEWHERE)
    assert api._jobs.registry.get(f.job_id).result()["reason"] == "changed"


def test_the_windows_whole_list_save_is_logged_with_a_copy_of_the_file_as_it_was(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    root = make_root(tmp_path)
    api, rec = make_api(root, api_class=CliApi)
    f = wait_job(api, rec, api.save_playlists(lines(POWER, HARD), api.playlists()["version"]))
    assert f.ok
    [logged] = oplog(root)
    assert (logged["operation"], logged["message"], logged["group"]) == ("playlist_saved",
                                                                        "Saved your playlists in the window.", "playlists")
    [copy] = copies(root)
    assert copy.read_text() == PLAYLISTS and copy.name == "2026-10-20_214700.txt"
    assert logged["undo"] == ["playlist", "edit", "--file", str(copy)] and logged["version"] == f.result["version"]
    assert newest(api)["undo"] == shlex.join([*logged["undo"], GUARD["playlists"], f.result["version"]])


def test_a_replacing_edit_keeps_a_copy_and_a_change_does_not(root, tmp_path):
    api, rec = make_api(root)
    other = tmp_path / "other.txt"
    other.write_text(f"Only = https://open.spotify.com/playlist/{ID3}\n")
    f = wait_job(api, rec, api.save_playlists(op={"op": "edit", "file": str(other)}))
    assert f.ok and root.playlists_file.read_text().endswith(f"Only = https://open.spotify.com/playlist/{ID3}\n")
    [copy] = copies(root)
    assert copy.read_text() == PLAYLISTS
    [logged] = oplog(root)
    assert (logged["operation"], logged["undo"]) == ("playlist_edit", ["playlist", "edit", "--file", str(copy)])
    assert logged["message"] == f"Replaced your playlists with the list in {other}."
    undone = wait_job(api, rec, api.save_playlists(op={"op": "edit", "file": str(copy)}))
    assert undone.ok and root.playlists_file.read_text() == PLAYLISTS  # the copy puts the file back, comments included


def test_a_save_that_changes_nothing_logs_nothing_and_keeps_no_copy(root):
    api, rec = make_api(root)
    f = wait_job(api, rec, api.save_playlists(lines(HARD, POWER), api.playlists()["version"]))
    assert f.ok and oplog(root) == [] and copies(root) == []
    f = wait_job(api, rec, api.save_playlists(op={"op": "enable", "playlist": "Hard_Bounce"}))  # already on
    assert f.ok and oplog(root) == [] and copies(root) == []


def test_a_save_the_rules_refuse_keeps_no_copy(root, monkeypatch):
    api, rec = make_api(root)
    version = api.playlists()["version"]
    f = wait_job(api, rec, api.save_playlists(lines(("not_lossless", HARD[1], True)), version))
    assert (f.ok, f.problem) == (False, "refused") and copies(root) == [] and oplog(root) == []
    real = pf.save

    def refuse(*args):
        raise pf.PlaylistsChanged(pf.CHANGED_ELSEWHERE)  # the file changed between the check and the write
    monkeypatch.setattr(pf, "save", refuse)
    f = wait_job(api, rec, api.save_playlists(lines(POWER, HARD), version))
    assert (f.ok, f.problem) == (False, "changed") and copies(root) == [] and oplog(root) == []
    monkeypatch.setattr(pf, "save", real)


def test_only_the_newest_twenty_copies_are_kept_by_time_then_number_not_by_name(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    root = make_root(tmp_path)
    api, _ = make_api(root)  # a fixed clock: every copy has the same stamp, then _2, _3 ... _21
    paths = [Path(api._keep_copy(f"{n}".encode())) for n in range(1, PLAYLIST_COPIES + 2)]
    assert paths[0].name == "2026-10-20_214700.txt" and paths[1].name == "2026-10-20_214700_2.txt"
    assert paths[-1].name == f"2026-10-20_214700_{PLAYLIST_COPIES + 1}.txt"
    kept = copies(root)
    assert len(kept) == PLAYLIST_COPIES and paths[0] not in kept  # the oldest went; `_10` did not sort before `_2`
    assert set(kept) == set(paths[1:]) and paths[-1].read_bytes() == f"{PLAYLIST_COPIES + 1}".encode()
    later = datetime(2026, 10, 21, 9, 0)
    api._svc.now = lambda: later
    newest_copy = Path(api._keep_copy(b"later"))
    assert newest_copy.name == "2026-10-21_090000.txt" and len(copies(root)) == PLAYLIST_COPIES
    assert paths[1] not in copies(root) and newest_copy in copies(root)
    (root.playlist_copies / "notes.txt").write_text("not a copy")  # a file that is no copy is left alone
    api._keep_copy(b"x")
    assert (root.playlist_copies / "notes.txt").exists()


def test_adding_liked_music_is_logged_with_its_undo(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    root = make_root(tmp_path)
    api, rec = make_api(root)
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}, read_liked_music=True))
    f = wait_job(api, rec, api.add_liked_music())
    assert f.ok and f.result == {"folder": "Liked_music"}
    [logged] = oplog(root)
    assert (logged["operation"], logged["message"], logged["undo"]) == (
        "liked_music_add", "Added Liked music as the playlist Liked_music.", ["playlist", "remove", "playlist:Liked_music"])
    assert logged["version"] == pf.load(root.playlists_file).version and logged["group"] == "playlists"


def test_an_add_of_liked_music_by_a_change_is_logged_the_same_way(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    root = make_root(tmp_path)
    api, rec = make_api(root)
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}, read_liked_music=True))
    f = wait_job(api, rec, api.save_playlists(op={"op": "add", "url": youtube_music.canonical_link("LM"), "folder": "Likes"}))
    assert f.ok and oplog(root)[0]["operation"] == "liked_music_add"
