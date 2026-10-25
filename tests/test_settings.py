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
