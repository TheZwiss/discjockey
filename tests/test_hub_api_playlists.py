from types import SimpleNamespace

import pytest
from hub_helpers import (ID1, ID2, PLAYLISTS, QOBUZ_ID, QOBUZ_LINK, QOBUZ_UNREADABLE, TRACKS, fake_qobuz, fake_spotify,
                         make_api, make_root, refreshed, track, wait_job)

from discjockey import sources
from discjockey.events import CancelToken
from discjockey.models import FetchedPlaylist, PlaylistInfo
from discjockey.sources.base import LoginState, SourceError
from discjockey.sources import spotify
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
