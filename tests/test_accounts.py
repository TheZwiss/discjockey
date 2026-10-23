"""accounts.py: names, limits, the §2 order of sources, browser logins and warning signs."""
import pytest

from discjockey import accounts as ac

QOBUZ_ZONES = [{"name": "careful", "from": 1, "to": 40}, {"name": "normal", "from": 41, "to": 60},
               {"name": "faster", "from": 61, "to": 79}, {"name": "fast", "from": 80, "to": 100},
               {"name": "risky", "from": 101, "to": 500}]


def test_qobuz_zones_and_assessment_stay_as_before():
    assert ac.zones("qobuz") == QOBUZ_ZONES
    expected = {1: 1, 40: 1, 41: 2, 60: 2, 61: 3, 80: 3, 81: 4, 100: 4, 101: 5, 500: 5}
    assert {limit: ac.assessment("qobuz", limit)["level"] for limit in expected} == expected
    assert ac.assessment("qobuz", 60) == {"level": 2, "label": "normal"}


def test_youtube_is_stricter():
    assert [(z["from"], z["to"]) for z in ac.zones("youtube")] == [(1, 20), (21, 30), (31, 45), (46, 60), (61, 500)]
    assert ac.assessment("youtube", 30) == {"level": 2, "label": "normal"}
    assert ac.assessment("youtube", 61) == {"level": 5, "label": "risky"}
    assert ac.DEFAULT_LIMITS == {"qobuz": 60, "youtube": 30, "soundcloud": 60}


def test_stream_rank_follows_the_spec_order():
    assert ac.stream_rank("youtube_music", {"youtube"}) == 3
    assert ac.stream_rank("soundcloud", {"soundcloud"}) == 4
    assert ac.stream_rank("youtube_music", set()) == 5
    assert ac.stream_rank("soundcloud", {"youtube"}) == 6
    assert ac.stream_rank("youtube", {"youtube", "soundcloud"}) == 7  # videos never use the login


def test_tiers_group_the_ranks():
    assert [ac.tier(r) for r in range(1, 8)] == [0, 0, 1, 1, 2, 2, 2]


@pytest.mark.parametrize("text,kind", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the "
     "authentication.", "bot_check"),
    ("ERROR: unable to download video data: HTTP Error 429: Too Many Requests", "rate_limited"),
    ("ERROR: [soundcloud] 123: HTTP Error 401: Unauthorized", "refused"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "refused"),
    ("[Errno 1] Operation not permitted: '/Users/x/Library/Containers/com.apple.Safari/Data/Library/Cookies/"
     "Cookies.binarycookies'", "cookies_unreadable"),
    ('could not find chrome cookies database in "/Users/x/Library/Application Support/Google/Chrome"',
     "cookies_unreadable"),
    ("ERROR: [youtube] abc: Video unavailable", None),
    ("ERROR: [soundcloud] 1429384756: Unable to download JSON metadata: HTTP Error 404: Not Found", None),
    ("ERROR: [soundcloud] https://soundcloud.com/dj-x/track-4290: Video unavailable", None),
    ("ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users. Use "
     "--cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ"
     "#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/"
     "yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies", None),
    ("ERROR: [soundcloud] 7: 429 Too Many Requests", "rate_limited"),
    ("ERROR: [youtube] abc: too many requests, try again later", "rate_limited"),
    ("ERROR: [youtube] abc: The provided YouTube account cookies are no longer valid. They have likely been rotated "
     "in the browser as a security measure.", "cookies_unreadable"),
    ("failed to read the Chrome Safe Storage password from the keychain", "cookies_unreadable"),
    ("<urlopen error [Errno 8] nodename nor servname provided, or not known>", None),
])
def test_warning_signs_in_ytdlp_errors(text, kind):
    assert ac.signal_of(RuntimeError(text)) == kind


def test_logins_for_ytdlp():
    assert ac.ytdlp_login("soundcloud", "firefox") == {"cookiesfrombrowser": ("firefox", None, None, None)}
    assert ac.ytdlp_login("soundcloud", "chrome", "Profile 2")["cookiesfrombrowser"] == ("chrome", "Profile 2", None, None)
    yt = ac.ytdlp_login("youtube", "chrome")
    assert yt["cookiesfrombrowser"] == ("chrome", None, None, None)
    assert yt["extractor_args"] == {"youtube": {"player_client": ["web_music", "default"]}}


def test_check_messages_say_what_to_do():
    ok = {"ok": True, "problem": None, "kbps": 256, "detail": ""}
    assert ac.check_message("youtube", "chrome", ok) == "✓ YouTube Premium works (256 kbps)."
    cookies = {"ok": False, "problem": "cookies_unreadable", "kbps": None, "detail": ""}
    assert "Full Disk Access" in ac.check_message("youtube", "safari", cookies)
    assert "“Always Allow”" in ac.check_message("youtube", "chrome", cookies)
    assert "Chrome Safe Storage" in ac.check_message("youtube", "chrome", cookies)
    assert "not logged in to SoundCloud in Firefox" in ac.check_message(
        "soundcloud", "firefox", {"ok": False, "problem": "not_logged_in", "kbps": None, "detail": ""})
