import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp
from hub_helpers import (ID1, ID2, PLAYLISTS, QOBUZ_ID, QOBUZ_LINK, QOBUZ_UNREADABLE, TRACKS, fake_qobuz, fake_spotify,
                         make_api, make_root, refreshed, track, wait_job)

from discjockey import playlists_file as pf
from discjockey import sources
from discjockey.events import CancelToken
from discjockey.models import FetchedPlaylist, PlaylistInfo
from discjockey.sources.base import LoginState, SourceError
from discjockey.sources import soundcloud, spotify, youtube_music
from discjockey.hub.api import rows_from, suggest_folder
from discjockey.library import run_lock

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


def test_add_a_playlist(root):
    api, rec = make_api(root)
    added = api.add_playlist(LINK3)
    assert added["ok"] and added["link"] == f"https://open.spotify.com/playlist/{ID3}" and added["tracks"] == 2
    assert added["readable"] and added["hint"] is None
    assert (added["playlist_id"], added["service"], added["service_name"]) == (ID3, "spotify", "Spotify")
    assert list(api._infos) == [ID3] and list(api._extra_tracks) == [ID3]  # a Spotify playlist keeps its bare id
    assert added["info"]["hint"] == "Follow ≠ own: make your own copy in Spotify."  # short enough for a row
    refused = api.add_playlist("https://open.spotify.com/album/x")
    assert refused["kind"] == "refused" and "service" not in refused


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
    assert list(api._infos) == [f"qobuz:{QOBUZ_ID}"] and list(api._extra_tracks) == [f"qobuz:{QOBUZ_ID}"]


def test_a_qobuz_playlist_qobuz_wont_show_answers_with_its_service(root, monkeypatch):
    fake_qobuz(monkeypatch, unreadable=True)
    api, rec = make_api(root)
    assert api.add_playlist(QOBUZ_LINK) == {"ok": False, "kind": "playlist_unreadable", "service": "qobuz",
                                            "message": QOBUZ_UNREADABLE}
    assert api._infos == {} and api._extra_tracks == {}


@pytest.mark.parametrize("kind,message", [
    ("offline", "Qobuz is not responding (HTTP 503). Try again later."),
    ("qobuz_login_failed", "Could not log in to Qobuz: the password was refused.")])
def test_a_qobuz_that_will_not_open_answers_with_its_service(root, monkeypatch, kind, message):
    fake_qobuz(monkeypatch, open_error=SourceError(message, kind, "qobuz"))
    api, rec = make_api(root)
    assert api.add_playlist(QOBUZ_LINK) == {"ok": False, "kind": kind, "service": "qobuz", "message": message}
    assert api._infos == {} and api._extra_tracks == {}


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
    assert api.add_playlist(link) == {"ok": False, "kind": "not_set_up", "service": service,
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
    assert api.add_playlist("https://soundcloud.com/you/likes") == {
        "ok": False, "kind": "playlist_unreadable", "service": "soundcloud", "message": "Use your profile's likes link."}
    assert api._infos == {} and api._extra_tracks == {}


def test_other_links_pass_expand_untouched(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    assert sources.expand(LINK3, root.support, CancelToken()) == LINK3  # Spotify defines no expand


def test_preview_reads_an_unread_playlist_of_a_service_that_needs_no_login(root, monkeypatch):
    fake_soundcloud(monkeypatch)
    api, rec = make_api(root)
    refreshed(api, rec)
    added = api.preview_playlist_change(lines(HARD, POWER, ("Example_Set", SC_SET, True)))
    assert added["ok"] and added["kind"] == "add" and added["new_downloads"] == 1


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
    c = api.preview_playlist_change(lines(HARD, POWER, ("Likes", "https://soundcloud.com/you/likes", True)))
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
    added = api.preview_playlist_change(lines(HARD, POWER, ("Q", QOBUZ_LINK, True)))
    assert added["ok"] and added["kind"] == "add" and added["new_downloads"] == 1
    fake_qobuz(monkeypatch, unreadable=True)
    other = api.preview_playlist_change(lines(HARD, POWER, ("Q2", "https://open.qobuz.com/playlist/900000002", True)))
    assert other["ok"] and other["kind"] == "unknown"  # nothing read for it: the page can't say what it adds
    fake_qobuz(monkeypatch, connected=False)  # not connected: no read either, and no failure
    none = api.preview_playlist_change(lines(HARD, ("Q3", "https://open.qobuz.com/playlist/900000003", True)))
    assert none["ok"] and none["kind"] == "unknown"


def test_preview_skips_a_service_that_will_not_open_and_reads_the_others(root, monkeypatch):
    fake_qobuz(monkeypatch, open_error=SourceError("Qobuz is not responding (HTTP 503). Try again later.", "offline",
                                                   "qobuz"))
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(HARD, ("New", LINK3, True), ("Q", QOBUZ_LINK, True)))
    assert c["ok"] and c["kind"] == "add" and c["new_downloads"] == 1  # Spotify's new playlist was read
    assert QOBUZ_LINK not in str(api._extra_tracks) and f"qobuz:{QOBUZ_ID}" not in api._extra_tracks


def test_preview_of_a_reorder_and_of_an_added_playlist(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(POWER, HARD))
    assert c["ok"] and c["kind"] == "moves" and [m["track_id"] for m in c["tidy"]["rows"]] == ["t2"]
    assert c["tidy"]["rows"][0]["to"].endswith("/not_lossless") and c["problem"] is None
    added = api.preview_playlist_change(lines(HARD, POWER, ("New", LINK3, True)))  # read once, right here
    assert added["kind"] == "add" and added["new_downloads"] == 1


def test_preview_says_what_is_wrong_with_the_lines(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    c = api.preview_playlist_change(lines(HARD, ("hard_bounce", LINK3, True)))
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


def test_saving_makes_the_preview_stale(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    wait_job(api, rec, api.save_playlists(lines(POWER, HARD), api.playlists()["version"]))
    assert api.sync_preview()["read_status"]["stale"] is True


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
W17 = ("Discjockey can't read your liked songs or Watch later. Add the songs to a playlist, set it to public or "
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
    assert api._infos[f"youtube_music:{YTM_ID}"].service == "youtube_music"


@pytest.mark.parametrize("pid, words", [("LM", W17), ("WL", W17), ("RDEXAMPLEmix0001", W18)])
def test_a_youtube_music_list_that_is_refused_answers_with_its_service(root, monkeypatch, pid, words):
    OneAnswerYDL.requested = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", OneAnswerYDL)
    api, rec = make_api(root)
    assert api.add_playlist(f"https://music.youtube.com/playlist?list={pid}") == {
        "ok": False, "kind": "playlist_unreadable", "service": "youtube_music", "message": words}
    assert OneAnswerYDL.requested == [] and api._infos == {} and api._extra_tracks == {}  # refused before any request


def test_your_own_likes_without_a_soundcloud_login_answer_w8(root, monkeypatch):
    api, rec = make_api(root)  # no SoundCloud account in the support folder: expand asks for none and says so
    answer = api.add_playlist("https://soundcloud.com/you/likes")
    assert answer == {"ok": False, "kind": "playlist_unreadable", "service": "soundcloud", "message": soundcloud.LIKES_HINT}
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
    assert calls == ["fetch"] and api._infos["soundcloud:example-label/sets/example-set"].name == "Example Set"
    assert api._extra_tracks["soundcloud:example-label/sets/example-set"][0].id == "900000101"


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
    assert api.add_playlist(SC_SET) == {"ok": False, "kind": "playlist_unreadable", "service": "soundcloud",
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
    assert api.add_playlist("https://soundcloud.com/you/likes") == {"ok": False, "kind": kind,
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
