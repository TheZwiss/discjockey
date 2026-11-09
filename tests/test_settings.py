import json
from datetime import date

import pytest

from discjockey.settings import Account, Settings, SettingsError, load_settings, save_settings


def test_defaults_when_missing(tmp_path):
    assert load_settings(tmp_path / "settings.json") == Settings(60, None, 0)


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(80, "2026-10-20", 15)
    save_settings(path, s)
    assert load_settings(path) == s
    assert not (tmp_path / "settings.json.tmp").exists()


def test_extra_applies_only_on_its_day():
    s = Settings(60, "2026-10-20", 15)
    assert s.extra_for(date(2026, 10, 20)) == 15
    assert s.extra_for(date(2026, 10, 21)) == 0


@pytest.mark.parametrize("text", ['{"daily_qobuz_limit": 0}', '{"daily_qobuz_limit": 501}', "not json",
                                  '{"extra_today": {"date": "2026-10-20", "amount": 999}}'])
def test_invalid_files_are_refused(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text)
    with pytest.raises(SettingsError):
        load_settings(path)


def test_an_older_file_without_accounts_still_loads(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"daily_qobuz_limit": 70, "extra_today": null}')
    s = load_settings(path)
    assert (s.daily_qobuz_limit, dict(s.accounts), s.qobuz_skipped) == (70, {}, False)


def test_accounts_roundtrip_and_no_cookie_is_stored(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(60, None, 0, {"youtube": Account("chrome", 30, "2026-10-20", 5),
                               "soundcloud": Account("firefox", 60)}, True)
    save_settings(path, s)
    assert load_settings(path) == s
    assert "cookie" not in path.read_text().lower()


def test_limit_and_extra_per_service():
    s = Settings(80, "2026-10-20", 10, {"youtube": Account("chrome", 25, "2026-10-20", 5)})
    day = date(2026, 10, 20)
    assert (s.limit_of("qobuz"), s.extra_of("qobuz", day)) == (80, 10)
    assert (s.limit_of("youtube"), s.extra_of("youtube", day)) == (25, 5)
    assert s.extra_of("youtube", date(2026, 10, 21)) == 0


def test_with_limit_keeps_everything_else():
    s = Settings(80, None, 0, {"youtube": Account("chrome", 30)})
    t = s.with_limit("youtube", 25, "2026-10-20", 10)
    assert t.daily_qobuz_limit == 80 and t.accounts["youtube"] == Account("chrome", 25, "2026-10-20", 10)
    u = t.with_limit("qobuz", 50, None, 0)
    assert u.accounts == t.accounts and u.daily_qobuz_limit == 50


def test_with_account_uses_the_default_limit_keeps_it_on_a_browser_change_and_forgets():
    s = Settings().with_account("youtube", "safari")
    assert s.accounts["youtube"] == Account("safari", 30)
    assert s.with_limit("youtube", 20, None, 0).with_account("youtube", "chrome").accounts["youtube"] == \
        Account("chrome", 20)
    assert dict(s.with_account("youtube", None).accounts) == {}


@pytest.mark.parametrize("text", [
    '{"accounts": {"tidal": {"browser": "chrome", "daily_limit": 30}}}',
    '{"accounts": {"youtube": {"browser": "netscape", "daily_limit": 30}}}',
    '{"accounts": {"youtube": {"browser": "chrome", "daily_limit": 0}}}',
    '{"accounts": {"youtube": {}}}',
])
def test_invalid_accounts_are_refused(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text)
    with pytest.raises(SettingsError):
        load_settings(path)


def test_qobuz_skipped_must_be_true_or_false(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"qobuz_skipped": "false"}')
    with pytest.raises(SettingsError, match="qobuz_skipped"):
        load_settings(path)


def test_warnings_seen_roundtrip_and_per_service(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(60).with_seen("qobuz", "2026-10-20T21:00:00").with_seen("youtube", "2026-10-19T08:00:00")
    s = s.with_seen("qobuz", "2026-10-21T09:00:00")
    save_settings(path, s)
    assert load_settings(path).warnings_seen == {"qobuz": "2026-10-21T09:00:00", "youtube": "2026-10-19T08:00:00"}


def test_warnings_seen_must_map_services_to_times(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"warnings_seen": {"qobuz": 5}}')
    with pytest.raises(SettingsError):
        load_settings(path)


CHECK = {"ok": True, "problem": None, "kbps": 256, "at": "2026-10-22T10:00:00"}


def test_profile_and_last_check_round_trip(tmp_path):
    f = tmp_path / "settings.json"
    s = Settings(accounts={"youtube": Account("chrome", 30, profile="Profile 2", last_check=CHECK)},
                 qobuz_last_check={"ok": False, "problem": "login_failed", "kbps": None, "at": "2026-10-22T09:00:00"})
    save_settings(f, s)
    assert load_settings(f) == s


def test_an_old_settings_file_without_profile_or_check_loads_unchanged(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text('{"daily_qobuz_limit": 60, "accounts": {"youtube": {"browser": "chrome", "daily_limit": 30}}}')
    s = load_settings(f)
    assert s.accounts["youtube"] == Account("chrome", 30) and s.qobuz_last_check is None


def test_another_browser_keeps_the_limit_and_drops_the_old_check():
    s = Settings(accounts={"youtube": Account("chrome", 45, last_check=CHECK)}).with_account("youtube", "brave", "Profile 1")
    assert s.accounts["youtube"] == Account("brave", 45, profile="Profile 1")


def test_with_check_per_service():
    s = Settings(accounts={"soundcloud": Account("chrome", 60)})
    assert s.with_check("soundcloud", CHECK).accounts["soundcloud"].last_check == CHECK
    assert s.with_check("qobuz", CHECK).qobuz_last_check == CHECK


@pytest.mark.parametrize("bad", ['"yes"', '{"ok": true}', '{"ok": "yes", "problem": null, "kbps": null, "at": "x"}'])
def test_a_broken_last_check_is_refused(tmp_path, bad):
    f = tmp_path / "settings.json"
    f.write_text('{"accounts": {"youtube": {"browser": "chrome", "daily_limit": 30, "last_check": %s}}}' % bad)
    with pytest.raises(SettingsError, match="last check"):
        load_settings(f)


def test_a_profile_must_be_a_name(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text('{"accounts": {"youtube": {"browser": "chrome", "daily_limit": 30, "profile": 2}}}')
    with pytest.raises(SettingsError, match="profile"):
        load_settings(f)


def test_spotify_skipped_roundtrips_and_must_be_true_or_false(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(path, Settings(spotify_skipped=True))
    assert load_settings(path).spotify_skipped is True
    path.write_text('{"daily_qobuz_limit": 70}')  # an older file: not skipped
    assert load_settings(path).spotify_skipped is False
    path.write_text('{"spotify_skipped": "yes"}')
    with pytest.raises(SettingsError, match="spotify_skipped"):
        load_settings(path)


def test_import_skipped_round_trips_defaults_to_false_and_must_be_true_or_false(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path).import_skipped is False
    path.write_text('{"daily_qobuz_limit": 60}')  # a settings file from before the import
    assert load_settings(path).import_skipped is False
    save_settings(path, Settings(import_skipped=True))
    assert load_settings(path).import_skipped is True
    path.write_text('{"import_skipped": "true"}')
    with pytest.raises(SettingsError, match="import_skipped"):
        load_settings(path)


def test_read_liked_music_round_trips_defaults_to_off_and_must_be_true_or_false(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path).read_liked_music is False
    path.write_text('{"daily_qobuz_limit": 60}')  # a settings file from before Liked music
    assert load_settings(path).read_liked_music is False
    save_settings(path, Settings(read_liked_music=True))
    assert load_settings(path).read_liked_music is True
    path.write_text('{"read_liked_music": "yes"}')
    with pytest.raises(SettingsError, match="read_liked_music"):
        load_settings(path)


def test_auto_upgrade_is_on_by_default_round_trips_and_must_be_true_or_false(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings().auto_upgrade is True and load_settings(path).auto_upgrade is True    # no file: on
    path.write_text('{"daily_qobuz_limit": 60}')                                            # a file without the key
    assert load_settings(path).auto_upgrade is True
    save_settings(path, Settings(auto_upgrade=False))
    assert load_settings(path).auto_upgrade is False
    assert json.loads(path.read_text())["auto_upgrade"] is False
    save_settings(path, Settings())
    assert load_settings(path).auto_upgrade is True
    for bad in ('"yes"', "1", "null"):
        path.write_text('{"auto_upgrade": %s}' % bad)
        with pytest.raises(SettingsError, match="auto_upgrade must be true or false"):
            load_settings(path)


def test_liked_music_is_read_only_with_the_choice_on_and_a_youtube_account():
    account = Account("chrome", 30)
    assert not Settings().reads_liked_music
    assert not Settings(read_liked_music=True).reads_liked_music  # no account to read it with
    assert not Settings(accounts={"youtube": account}).reads_liked_music
    assert Settings(accounts={"youtube": account}, read_liked_music=True).reads_liked_music
    assert not Settings(accounts={"soundcloud": account}, read_liked_music=True).reads_liked_music


def test_forgetting_the_youtube_login_turns_liked_music_off_for_good():
    s = Settings(accounts={"youtube": Account("chrome", 30), "soundcloud": Account("chrome", 60)},
                 read_liked_music=True)
    assert s.with_account("soundcloud", None).read_liked_music is True  # another account's login is none of its business
    forgotten = s.with_account("youtube", None)
    assert forgotten.read_liked_music is False and "youtube" not in forgotten.accounts
    assert forgotten.with_account("youtube", "chrome").read_liked_music is False  # signing in again does not resume
    assert s.with_account("youtube", "firefox").read_liked_music is True  # another browser keeps the choice


FREE = {"ok": False, "problem": "no_premium", "kbps": 129, "at": "2026-10-20T21:47:00"}
PREMIUM = {"ok": True, "problem": None, "kbps": 256, "at": "2026-10-20T21:47:00"}


def test_a_youtube_login_without_premium_is_no_download_account():
    s = Settings(accounts={"youtube": Account("chrome", 30, last_check=FREE),
                           "soundcloud": Account("firefox", 60, last_check=FREE)})
    assert list(s.download_accounts) == ["soundcloud"]  # SoundCloud tries Go+ on every track on purpose
    assert "youtube" in s.accounts and s.reads_liked_music is False
    assert Settings(accounts=s.accounts, read_liked_music=True).reads_liked_music


def test_every_other_youtube_login_downloads():
    for check in (PREMIUM, None, {**FREE, "problem": "not_logged_in"}, {**FREE, "problem": "failed"}):
        s = Settings(accounts={"youtube": Account("chrome", 30, last_check=check)})
        assert list(s.download_accounts) == ["youtube"], check


def test_a_free_youtube_login_stays_out_of_downloads_through_checks_that_say_nothing_about_premium(tmp_path):
    s = Settings(accounts={"youtube": Account("chrome", 30)}).with_check("youtube", FREE)
    assert s.accounts["youtube"].liked_only and "youtube" not in s.download_accounts
    for problem in ("failed", "not_logged_in", "cookies_unreadable"):
        s = s.with_check("youtube", {**FREE, "problem": problem})
        assert "youtube" not in s.download_accounts, problem  # offline or logged out: still no Premium
    path = tmp_path / "settings.json"
    save_settings(path, s)
    assert "youtube" not in load_settings(path).download_accounts  # kept across a restart
    s = s.with_check("youtube", PREMIUM)  # Premium found: it downloads again, and stays a download account
    assert list(s.download_accounts) == ["youtube"]
    assert list(s.with_check("youtube", {**FREE, "problem": "failed"}).download_accounts) == ["youtube"]
    # a Premium login that lapses is liked-only until a good check
    assert "youtube" not in s.with_check("youtube", FREE).download_accounts
    # another browser or profile is another login: unchecked, so it downloads until its check says
    assert list(s.with_check("youtube", FREE).with_account("youtube", "firefox").download_accounts) == ["youtube"]


def test_a_soundcloud_check_never_marks_the_login_liked_only():
    s = Settings(accounts={"soundcloud": Account("chrome", 30)}).with_check("soundcloud", FREE)
    assert not s.accounts["soundcloud"].liked_only and list(s.download_accounts) == ["soundcloud"]
