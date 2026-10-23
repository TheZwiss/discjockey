import os
import plistlib
from pathlib import Path

from discjockey import browsers
from browser_helpers import (CHROME, FIREFOX, SAFARI, chrome_cookies, copy_db_files, firefox_cookies,
                             firefox_profile, local_state, wal_only_firefox_db)

LS_PLIST = "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"


def write_handlers(home, handlers):
    p = home / LS_PLIST
    p.parent.mkdir(parents=True)
    p.write_bytes(plistlib.dumps({"LSHandlers": handlers}))


def test_installed_reads_applications(tmp_path):
    apps = tmp_path / "Applications"
    (apps / "Google Chrome.app").mkdir(parents=True)
    (apps / "Safari.app").mkdir()
    assert browsers.installed(tmp_path, apps=(apps,)) == ["safari", "chrome"]


def test_installed_also_looks_in_the_users_applications(tmp_path):
    (tmp_path / "Applications/Firefox.app").mkdir(parents=True)
    assert browsers.installed(tmp_path, apps=(tmp_path / "nowhere",)) == ["firefox"]


def test_default_browser_from_launch_services(tmp_path):
    write_handlers(tmp_path, [{"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
                              {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.google.chrome"}])
    assert browsers.default_browser(tmp_path) == "chrome"


def test_default_browser_bundle_id_is_case_insensitive(tmp_path):
    write_handlers(tmp_path, [{"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.Google.Chrome"}])
    assert browsers.default_browser(tmp_path) == "chrome"


def test_default_browser_falls_back_to_http(tmp_path):
    write_handlers(tmp_path, [{"LSHandlerURLScheme": "http", "LSHandlerRoleAll": "org.mozilla.firefox"}])
    assert browsers.default_browser(tmp_path) == "firefox"


def test_default_browser_is_safari_without_a_web_handler(tmp_path):
    write_handlers(tmp_path, [{"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"}])
    assert browsers.default_browser(tmp_path) == "safari"


def test_default_browser_none_when_the_plist_cannot_be_read(tmp_path):
    assert browsers.default_browser(tmp_path) is None
    p = tmp_path / LS_PLIST
    p.parent.mkdir(parents=True)
    p.write_bytes(b"not a plist")
    assert browsers.default_browser(tmp_path) is None


def test_default_browser_none_for_a_browser_we_do_not_know(tmp_path):
    write_handlers(tmp_path, [{"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "company.thebrowser.browser"}])
    assert browsers.default_browser(tmp_path) is None


def test_chrome_profiles_from_local_state(tmp_path):
    local_state(tmp_path, {"Default": "Person 1", "Profile 2": "DJ"})
    (tmp_path / CHROME / "Default").mkdir(parents=True)
    (tmp_path / CHROME / "Profile 2").mkdir()
    assert browsers.profiles("chrome", tmp_path) == [{"id": "Default", "name": "Person 1"},
                                                    {"id": "Profile 2", "name": "DJ"}]


def test_chromium_without_local_state_uses_the_default_folder(tmp_path):
    (tmp_path / CHROME / "Default").mkdir(parents=True)
    assert browsers.profiles("chrome", tmp_path) == [{"id": "Default", "name": "Default"}]


def test_a_login_found_in_the_second_profile(tmp_path):
    local_state(tmp_path, {"Default": "Person 1", "Profile 2": "DJ"})
    chrome_cookies(tmp_path, "Default", [(".google.com", "NID")])
    chrome_cookies(tmp_path, "Profile 2", [(".youtube.com", "SAPISID")], network=True)
    assert browsers.logins("youtube", "chrome", tmp_path) == {"readable": True, "problem": None,
                                                             "profiles": ["Profile 2"]}
    assert browsers.logins("soundcloud", "chrome", tmp_path)["profiles"] == []


def test_the_newer_cookie_file_wins(tmp_path):
    local_state(tmp_path, {"Default": "Person 1"})
    old = chrome_cookies(tmp_path, "Default", [(".youtube.com", "SAPISID")], network=True)
    new = chrome_cookies(tmp_path, "Default", [(".google.com", "NID")])
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    assert browsers.logins("youtube", "chrome", tmp_path)["profiles"] == []
    os.utime(old, (3_000, 3_000))
    assert browsers.logins("youtube", "chrome", tmp_path)["profiles"] == ["Default"]


def test_firefox_profiles_and_login(tmp_path):
    firefox_profile(tmp_path, "default-release", "Profiles/abcd.default-release",
                    [(".soundcloud.com", "oauth_token")])
    assert browsers.profiles("firefox", tmp_path) == [{"id": "abcd.default-release", "name": "default-release"}]
    assert browsers.logins("soundcloud", "firefox", tmp_path)["profiles"] == ["abcd.default-release"]
    assert browsers.logins("youtube", "firefox", tmp_path)["profiles"] == []


def test_firefox_absolute_profile_keeps_its_full_path(tmp_path):
    folder = tmp_path / "elsewhere" / "xyz.work"
    firefox_profile(tmp_path, "work", str(folder), [(".youtube.com", "LOGIN_INFO")], relative=False)
    assert browsers.profiles("firefox", tmp_path) == [{"id": str(folder), "name": "work"}]
    assert browsers.logins("youtube", "firefox", tmp_path)["profiles"] == [str(folder)]


def test_firefox_profiles_ini_with_a_percent_sign(tmp_path):
    (tmp_path / FIREFOX).mkdir(parents=True)
    (tmp_path / FIREFOX / "profiles.ini").write_text("[Profile0]\nName=100% me\nIsRelative=1\nPath=Profiles/a.b\n")
    assert browsers.profiles("firefox", tmp_path) == [{"id": "a.b", "name": "100% me"}]


def test_a_login_only_in_the_wal_is_found(tmp_path):
    live = tmp_path / "live" / "cookies.sqlite"
    con = wal_only_firefox_db(live, [(".soundcloud.com", "oauth_token")])
    assert live.with_name("cookies.sqlite-wal").exists()
    try:
        folder = firefox_profile(tmp_path, "p", "Profiles/wal.p")
        copy_db_files(live, folder)
    finally:
        con.close()
    assert (folder / "cookies.sqlite-wal").exists()
    assert browsers.logins("soundcloud", "firefox", tmp_path)["profiles"] == ["wal.p"]


def test_the_original_database_is_left_alone(tmp_path):
    db = firefox_cookies(tmp_path / "c.sqlite", [(".soundcloud.com", "oauth_token")])
    before = db.read_bytes()
    assert browsers._names_from_sqlite(db, "SELECT host, name FROM moz_cookies") == [
        (".soundcloud.com", "oauth_token")]
    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.sqlite"]


def test_a_locked_or_broken_database_is_locked_not_a_crash(tmp_path):
    local_state(tmp_path, {"Default": "Person 1"})
    d = tmp_path / CHROME / "Default"
    d.mkdir(parents=True)
    (d / "Cookies").write_bytes(b"not a database")
    assert browsers.logins("youtube", "chrome", tmp_path) == {"readable": False, "problem": "locked", "profiles": []}


def test_safari_without_full_disk_access(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(browsers, "_read_bytes", denied)
    f = tmp_path / SAFARI
    f.parent.mkdir(parents=True)
    f.write_bytes(b"cook")
    assert browsers.logins("youtube", "safari", tmp_path) == {"readable": False, "problem": "no_access", "profiles": []}


def test_safari_login_found(tmp_path, monkeypatch):
    f = tmp_path / SAFARI
    f.parent.mkdir(parents=True)
    f.write_bytes(b"cook")
    monkeypatch.setattr(browsers, "_safari_names", lambda data: [(".youtube.com", "LOGIN_INFO")])
    assert browsers.logins("youtube", "safari", tmp_path)["profiles"] == [None]


def test_safari_file_that_does_not_parse_is_locked(tmp_path):
    f = tmp_path / SAFARI
    f.parent.mkdir(parents=True)
    f.write_bytes(b"this is not a binarycookies file")
    assert browsers.logins("youtube", "safari", tmp_path) == {"readable": False, "problem": "locked", "profiles": []}


def test_safari_parse_error_of_any_kind_is_locked(tmp_path, monkeypatch):
    f = tmp_path / SAFARI
    f.parent.mkdir(parents=True)
    f.write_bytes(b"cook")

    def boom(data):
        raise RuntimeError("yt-dlp changed")
    monkeypatch.setattr("yt_dlp.cookies.parse_safari_cookies", boom)
    assert browsers.logins("youtube", "safari", tmp_path)["problem"] == "locked"


def test_safari_without_a_cookie_file_has_no_login(tmp_path):
    assert browsers.logins("youtube", "safari", tmp_path) == {"readable": True, "problem": None, "profiles": []}


def test_no_browser_data_at_all(tmp_path):
    assert browsers.logins("youtube", "brave", tmp_path) == {"readable": True, "problem": None, "profiles": []}
    assert browsers.profiles("edge", tmp_path) == []


def test_unknown_browser_is_readable_without_profiles(tmp_path):
    assert browsers.logins("youtube", "arc", tmp_path) == {"readable": True, "problem": None, "profiles": []}
    assert browsers.profiles("arc", tmp_path) == []
