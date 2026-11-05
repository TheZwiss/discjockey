"""The Liked music bridge (sources-round D5-D9, I3): Settings' choice, "Add Liked music to Playlists", the pasted LM link
and the shapes the page reads (`setup_status().youtube_music`, `playlists()` rows' `needs_setting`). Offline: a stub
yt-dlp serves the recorded album page as Liked music."""
import json
from datetime import datetime
from pathlib import Path

import pytest
import yt_dlp
from hub_helpers import fake_spotify, make_api, make_root, wait_job

from discjockey import library, pacing
from discjockey import playlists_file as pf
from discjockey.settings import Account, Settings, load_settings, save_settings
from discjockey.sources import youtube_music

LM_LINK = "https://music.youtube.com/playlist?list=LM"
LM_FIXTURE = Path(__file__).parent / "fixtures" / "youtube_music" / "album_playlist.json"
SETTING_OFF = "Reading your Liked music is off. Turn it on in Settings."


class LikedYDL:
    created: list = []
    requested: list = []
    error: Exception | None = None

    def __init__(self, opts):
        LikedYDL.created.append(opts)

    def extract_info(self, url, download=True, process=True, **kwargs):
        LikedYDL.requested.append(url)
        if LikedYDL.error is not None:
            raise LikedYDL.error
        return json.loads(LM_FIXTURE.read_text())

    def close(self):
        pass


@pytest.fixture
def root(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    LikedYDL.created, LikedYDL.requested, LikedYDL.error = [], [], None
    monkeypatch.setattr(yt_dlp, "YoutubeDL", LikedYDL)
    return make_root(tmp_path)


def settings(root, on=True, account=True):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)} if account else {},
                                               read_liked_music=on))


def listed(root, off=False):
    with root.playlists_file.open("a") as f:
        f.write(f"{'#off# ' if off else ''}Liked_music = {LM_LINK}\n")


# --- settings: the choice and the status block ---------------------------------------------------------------------

def test_status_says_whether_liked_music_is_on_can_be_turned_on_and_is_listed(root):
    api, _ = make_api(root)
    assert api.setup_status()["youtube_music"] == {"liked_music": False, "can_turn_on": False, "listed": False}
    settings(root, on=False)
    assert api.setup_status()["youtube_music"] == {"liked_music": False, "can_turn_on": True, "listed": False}
    settings(root)
    listed(root, off=True)  # an off line is listed too
    assert api.setup_status()["youtube_music"] == {"liked_music": True, "can_turn_on": True, "listed": True}


def test_turning_it_on_without_a_youtube_account_is_refused(root):
    api, rec = make_api(root)
    f = wait_job(api, rec, api.set_read_liked_music(True))
    assert (f.ok, f.problem) == (False, "not_set_up") and "Sign in to YouTube Premium first" in f.message
    assert not load_settings(root.settings_file).read_liked_music


def test_the_choice_is_saved_and_turning_it_off_leaves_playlists_txt_alone(root):
    api, rec = make_api(root)
    settings(root, on=False)
    listed(root)
    before = root.playlists_file.read_bytes()
    assert wait_job(api, rec, api.set_read_liked_music(True)).ok
    assert load_settings(root.settings_file).read_liked_music
    assert wait_job(api, rec, api.set_read_liked_music(False)).ok
    assert not load_settings(root.settings_file).read_liked_music
    assert root.playlists_file.read_bytes() == before
    assert load_settings(root.settings_file).accounts.keys() == {"youtube"}  # nothing else changed


def test_the_choice_must_be_true_or_false(root):
    api, _ = make_api(root)
    answer = api.set_read_liked_music("yes")
    assert answer["ok"] is False and answer["kind"] == "refused"


# --- Add Liked music to Playlists -----------------------------------------------------------------------------------

def test_add_liked_music_appends_exactly_one_line_at_the_end(root):
    api, rec = make_api(root)
    settings(root)
    version = api.playlists()["version"]
    before = root.playlists_file.read_text()
    f = wait_job(api, rec, api.add_liked_music())
    assert f.ok and f.result == {"folder": "Liked_music"}
    after = root.playlists_file.read_text()
    assert after == before + f"Liked_music = {LM_LINK}\n"
    page = api.playlists()
    assert page["version"] != version and [r["folder"] for r in page["rows"]][-1] == "Liked_music"
    assert page["rows"][-1]["playlist_id"] == "youtube_music:LM" and page["rows"][-1]["enabled"]
    assert page["rows"][-1]["needs_setting"] is None


def test_add_liked_music_twice_or_with_an_off_line_says_exists_and_writes_nothing(root):
    api, rec = make_api(root)
    settings(root)
    assert wait_job(api, rec, api.add_liked_music()).ok
    once = root.playlists_file.read_bytes()
    f = wait_job(api, rec, api.add_liked_music())
    assert (f.ok, f.problem) == (False, "exists") and root.playlists_file.read_bytes() == once
    # an off line counts as listed
    root.playlists_file.write_bytes(once.replace(b"Liked_music =", b"#off# Liked_music ="))
    off = root.playlists_file.read_bytes()
    f = wait_job(api, rec, api.add_liked_music())
    assert (f.ok, f.problem) == (False, "exists") and root.playlists_file.read_bytes() == off


def test_add_liked_music_refuses_while_the_choice_is_off(root):
    api, rec = make_api(root)
    before = root.playlists_file.read_bytes()
    for on, account in ((False, True), (True, False)):
        settings(root, on=on, account=account)
        f = wait_job(api, rec, api.add_liked_music())
        assert (f.ok, f.problem, f.message) == (False, "setting_off", SETTING_OFF)
    assert root.playlists_file.read_bytes() == before


def test_add_liked_music_takes_a_free_folder_name(root):
    api, rec = make_api(root)
    settings(root)
    root.playlists_file.write_text(root.playlists_file.read_text() + "Liked_music = https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M\n")
    f = wait_job(api, rec, api.add_liked_music())
    assert f.ok and f.result == {"folder": "Liked_music_2"}
    assert root.playlists_file.read_text().splitlines()[-1] == f"Liked_music_2 = {LM_LINK}"


# --- pasting the link -----------------------------------------------------------------------------------------------

def test_pasting_liked_music_while_it_is_off_answers_a_needs_a_setting_form(root):
    api, _ = make_api(root)
    for on, account in ((False, True), (True, False)):
        settings(root, on=on, account=account)
        assert api.add_playlist(LM_LINK) == {
            "ok": False, "kind": "setting_off", "setting": "read_liked_music", "service": "youtube_music",
            "message": SETTING_OFF}
    assert LikedYDL.created[:0] == [] and LikedYDL.requested == [] and api._infos == {} and api._extra_tracks == {}


def test_pasting_liked_music_while_it_is_on_reads_it_with_the_login(root):
    api, _ = make_api(root)
    settings(root)
    added = api.add_playlist(LM_LINK)
    assert added["ok"] and added["readable"] and added["tracks"] == 3
    assert (added["playlist_id"], added["service"], added["link"]) == ("youtube_music:LM", "youtube_music", LM_LINK)
    assert added["info"]["name"] == "Example Album"
    assert sum("cookiesfrombrowser" in o for o in LikedYDL.created) == 1 and set(LikedYDL.requested) == {LM_LINK}


def test_pasting_liked_music_while_the_account_is_paused_reads_nothing(root):
    api, _ = make_api(root)
    settings(root)
    state = library.load_state(root)
    pacing.record_signal(state, "bot_check", "m", datetime.combine(api._today(), datetime.min.time()), "youtube")
    library.save_state(root, state)
    answer = api.add_playlist(LM_LINK)
    assert (answer["ok"], answer["kind"], answer["message"]) == (False, "offline", youtube_music.LIKED_RESTING)
    assert LikedYDL.created == [] and LikedYDL.requested == []


def test_a_bot_check_met_while_pasting_is_recorded_as_the_accounts_warning_sign(root):
    api, _ = make_api(root)
    settings(root)
    LikedYDL.error = Exception("Sign in to confirm you're not a bot")
    answer = api.add_playlist(LM_LINK)
    assert (answer["ok"], answer["kind"]) == (False, "offline")
    signs = library.load_state(root)["youtube_usage"]["signals"]
    assert [s["kind"] for s in signs] == ["bot_check"]
    assert pacing.account_paused(library.load_state(root), "youtube", datetime.now().date())  # the real clock here


def test_a_changed_plan_preview_does_not_read_a_liked_music_line_that_is_off(root):
    api, _ = make_api(root)
    settings(root, on=False)
    rows = [{"folder": "Liked_music", "link": LM_LINK, "enabled": True}]
    answer = api.preview_playlist_change(rows)
    assert answer["ok"] and LikedYDL.requested == []
    assert not any("cookiesfrombrowser" in o for o in LikedYDL.created)


# --- playlists(): a listed line while it is off --------------------------------------------------------------------

def test_a_listed_liked_music_line_says_it_needs_the_setting_while_it_is_off(root):
    api, _ = make_api(root)
    listed(root)
    rows = api.playlists()["rows"]
    assert [r["needs_setting"] for r in rows] == [None, None, "read_liked_music"]
    settings(root, on=False)
    assert api.playlists()["rows"][-1]["needs_setting"] == "read_liked_music"
    settings(root)
    assert [r["needs_setting"] for r in api.playlists()["rows"]] == [None, None, None]


def test_an_off_liked_music_line_is_in_the_page_like_any_switched_off_row(root):
    api, _ = make_api(root)
    listed(root, off=True)
    row = api.playlists()["rows"][-1]
    assert (row["folder"], row["enabled"], row["needs_setting"]) == ("Liked_music", False, "read_liked_music")
    assert pf.lists_liked_music(pf.load(root.playlists_file).rows)
