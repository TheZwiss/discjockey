"""The download sources with an account and a daily limit (spec sources-and-limits §2-§5): Qobuz, YouTube Music with
Premium and SoundCloud Go+. Names, default limits and zones, the order of every source by quality, the browser logins
for yt-dlp and the warning signs in yt-dlp's errors. No I/O here."""
from __future__ import annotations

SERVICES = ("qobuz", "youtube", "soundcloud")  # in quality order; Qobuz logs in through streamrip
ACCOUNTS = ("youtube", "soundcloud")  # logged in through the colleague's browser (yt-dlp reads its cookies)
SERVICE_NAMES = {"qobuz": "Qobuz", "youtube": "YouTube Premium", "soundcloud": "SoundCloud Go+"}
ACCOUNT_OF = {"youtube_music": "youtube", "soundcloud": "soundcloud"}  # a fallback source -> the account it uses
DEFAULT_LIMITS = {"qobuz": 60, "youtube": 30, "soundcloud": 60}
MAX_LIMIT = 500
ZONE_NAMES = ("careful", "normal", "faster", "fast", "risky")
ZONE_TOPS = {"qobuz": (40, 60, 79, 100), "youtube": (20, 30, 45, 60), "soundcloud": (40, 60, 79, 100)}
ASSESSMENT_TOPS = {"qobuz": (40, 60, 80, 100), "youtube": (20, 30, 45, 60), "soundcloud": (40, 60, 80, 100)}
BROWSERS = {"safari": "Safari", "chrome": "Chrome", "firefox": "Firefox", "brave": "Brave", "edge": "Microsoft Edge"}
ACCOUNT_KBPS = 256
PREMIUM_MIN_KBPS = 200  # a stream at least this good came through the account (the free ones stay at about 160)
RANK_ACCOUNT = {"youtube_music": 3, "soundcloud": 4}  # §2; 1 Qobuz, 2 a lossless artist download
RANK_FREE = {"youtube_music": 5, "soundcloud": 6, "youtube": 7}
SIGNALS = ("cookies_unreadable", "bot_check", "rate_limited", "refused", "premium_missing", "download_rejected",
           "auto_stop")
SERVICE_SIGNALS = {
    "qobuz": ("login_failed", "search_failed", "download_rejected", "preview_only", "duration_mismatch", "auto_stop"),
    "youtube": SIGNALS,
    "soundcloud": tuple(s for s in SIGNALS if s != "bot_check"),
}


def zones(service: str) -> list[dict]:
    """[{name, from, to}] for the hub's slider; "risky" runs up to MAX_LIMIT."""
    out, start = [], 1
    for name, top in zip(ZONE_NAMES, (*ZONE_TOPS[service], MAX_LIMIT)):
        out.append({"name": name, "from": start, "to": top})
        start = top + 1
    return out


def assessment(service: str, limit: int) -> dict:
    """A guess, labelled as one: 1 careful ... 5 risky, by the service's own thresholds."""
    for level, (top, label) in enumerate(zip(ASSESSMENT_TOPS[service], ZONE_NAMES), 1):
        if limit <= top:
            return {"level": level, "label": label}
    return {"level": 5, "label": "risky"}


def stream_rank(source: str, usable: set[str] | frozenset[str]) -> int:
    """§2 rank of a YouTube Music, SoundCloud or YouTube match (lower is better). `usable`: the account services that
    can download right now (set up, today's limit not used up, not paused)."""
    if ACCOUNT_OF.get(source) in usable:
        return RANK_ACCOUNT[source]
    return RANK_FREE[source]


def tier(rank: int) -> int:
    """0 lossless (ranks 1-2), 1 ~256 kbps through an account (3-4), 2 free streams (5-7). The wait rule compares
    tiers, so YouTube Premium and SoundCloud Go+ stand in for each other."""
    return 0 if rank <= 2 else 1 if rank <= 4 else 2


# The cookie that says a browser is logged in to the service: (domain, names). Read by name only (browsers.py, and
# FallbackSource.check_account); a value is never shown or kept.
LOGIN_COOKIES = {"youtube": (".youtube.com", ("SAPISID", "__Secure-3PAPISID", "LOGIN_INFO")),
                 "soundcloud": (".soundcloud.com", ("oauth_token",))}


def ytdlp_login(service: str, browser: str, profile: str | None = None) -> dict:
    """yt-dlp options that use the colleague's browser login (in that browser profile; None: the default one): only
    for a matched track's formats and its download, never for a search. YouTube's premium formats (141, 774) need the
    web_music client since yt-dlp 2025.08."""
    opts: dict = {"cookiesfrombrowser": (browser, profile, None, None)}
    if service == "youtube":
        opts["extractor_args"] = {"youtube": {"player_client": ["web_music", "default"]}}
    return opts


def signal_of(error: object) -> str | None:
    """The warning sign in a yt-dlp error, or None for anything else (a network drop, a removed upload)."""
    text = str(error).lower()
    if "not a bot" in text:  # first: YouTube's bot check also mentions --cookies
        return "bot_check"
    if "http error 429" in text or "too many requests" in text:  # not a bare 429: SoundCloud ids can contain it
        return "rate_limited"
    if any(k in text for k in ("http error 401", "http error 403", "unauthorized", "forbidden")):
        return "refused"
    # "Use --cookies ..." is yt-dlp's advice on an upload that needs a login (an age gate), not a login that failed
    if ("cookie" in text and "--cookies" not in text) or "keychain" in text or "safe storage" in text:
        return "cookies_unreadable"
    return None


def check_message(service: str, browser: str, check: dict) -> str:
    """What setup's "Check" found, in plain words (check: {"ok", "problem", "kbps", "detail"})."""
    name, where = SERVICE_NAMES[service], BROWSERS[browser]
    site = "YouTube" if service == "youtube" else "SoundCloud"
    if check["ok"]:
        return f"✓ {name} works ({check['kbps']} kbps)."
    problem = check["problem"]
    if problem == "cookies_unreadable":
        if browser == "safari":
            return ("macOS didn't let Discjockey read Safari's login. Give Discjockey Full Disk Access (System Settings → "
                    "Privacy & Security → Full Disk Access), or pick another browser.")
        return (f"macOS didn't let Discjockey read {where}'s login. Check again and click “Always Allow” when macOS asks "
                f"about “{where} Safe Storage”.")
    if problem == "not_logged_in":
        return f"You're not logged in to {site} in {where}. Log in there, then check again."
    if problem == "no_premium":
        kbps = check["kbps"] or "?"
        if service == "youtube":
            return (f"Logged in, but YouTube gives this account no Premium formats ({kbps} kbps). Discjockey keeps using "
                    "YouTube Music without the login.")
        return (f"Logged in, but the test track came at {kbps} kbps. Either the account has no Go+, or this track has "
                "no Go+ stream. Discjockey tries Go+ on every track and shows what it got.")
    return f"The check didn't work ({check.get('detail') or 'no answer'}). Try again in a minute."
