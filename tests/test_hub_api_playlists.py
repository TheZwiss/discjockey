import pytest
from hub_helpers import ID1, ID2, PLAYLISTS, TRACKS, fake_spotify, make_api, make_root, refreshed, track, wait_job

from discjockey import spotify
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
    assert api.add_playlist("https://open.spotify.com/album/x")["kind"] == "refused"


def test_a_followed_playlist_is_not_readable(root, monkeypatch):
    monkeypatch.setattr(spotify, "playlist_info", lambda s, pid, me: spotify.PlaylistInfo(
        pid, "Their list", "someone", "Someone", False, None, 30, False))
    api, rec = make_api(root)
    added = api.add_playlist(LINK3)
    assert not added["readable"] and added["tracks"] is None and "Follow ≠ own" in added["hint"]


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
    assert api.sync_preview()["spotify"]["stale"] is True


@pytest.mark.parametrize("name,folder", [("Hard Bounce 2026", "Hard_Bounce_2026"), ("POWERTRANCE 🔥", "POWERTRANCE"),
                                         ("a/b: c", "ab_c"), ("", "New_playlist"), ("not_lossless", "New_playlist")])
def test_suggest_folder(name, folder):
    assert suggest_folder(name) == folder


def test_rows_from_checks_the_links():
    with pytest.raises(ValueError, match="not a Spotify playlist link"):
        rows_from([{"folder": "A", "link": "https://example.com"}])
