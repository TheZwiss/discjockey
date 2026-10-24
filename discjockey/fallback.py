"""Fallback sources through yt-dlp (as a library): YouTube Music, SoundCloud, YouTube. Also the artists' own free
downloads that SoundCloud tracks link to (a download gate on hypeddit etc., or SoundCloud's own download button)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote_plus, urlparse

import yt_dlp
import yt_dlp.cookies
from yt_dlp.extractor.soundcloud import SoundcloudIE
from yt_dlp.utils import download_range_func

from .accounts import ACCOUNT_OF, LOGIN_COOKIES, PREMIUM_MIN_KBPS, signal_of, ytdlp_login
from .events import Emit, Message, no_emit
from .models import SOURCE_NAMES, Candidate, Protected, SourceTrack

YTM_SEARCH = "https://music.youtube.com/search?q="
# Download gates: the artist's free download after a follow, like or e-mail. SoundCloud shows them as the track's
# "buy" link, mostly titled "Free Download"; these hosts are gates whatever the title says.
GATE_HOSTS = ("hypeddit.com", "toneden.io", "downloadgater.com", "gaterush.me", "managerone.io", "droploud.com",
              "fanlink.to", "gate.fm", "click.dj")
# setup's "Check": a well-known song, searched without the login; its formats are then listed with the login
CHECK_SONG = "Daft Punk One More Time"
CHECK_QUERY = {"youtube": f"{YTM_SEARCH}{quote_plus(CHECK_SONG)}#songs", "soundcloud": f"scsearch3:{CHECK_SONG}"}
CHECK_SOURCE = {"youtube": "youtube_music", "soundcloud": "soundcloud"}
SECTION_FORMAT = "bestaudio[protocol!=http_dash_segments]/bestaudio/best"  # for the "Wrong song?" preview clips


def short_error(e: Exception) -> str:
    """The first line of an error, at most 200 characters: what a warning sign or a debug line keeps of it."""
    return (str(e).splitlines() or [type(e).__name__])[0][:200]


def drm_protected(e: Exception) -> bool:
    """yt-dlp refuses DRM-protected uploads ("This video is DRM protected"); Discjockey never works around that."""
    return "drm protected" in str(e).lower()


class SoundcloudDrmIE(SoundcloudIE):
    """yt-dlp's SoundCloud extractor, which also notes what it leaves out silently: a Go+ ("hq") stream that the track
    JSON (already fetched, no extra request) lists only DRM-protected (protocol ctr-/cbc-encrypted-hls). yt-dlp
    raises "DRM protected" only when every stream is protected; otherwise it lists the free ones as if there were no
    Go+ stream. Discjockey never uses or decrypts the protected stream; it only tells it apart from a missing one."""
    drm_premium = False

    @classmethod
    def ie_key(cls):
        return SoundcloudIE.ie_key()  # takes the place of yt-dlp's own SoundCloud extractor

    def _extract_info_dict(self, info, *args, **kwargs):
        self.drm_premium = any(
            t.get("quality") == "hq" and str((t.get("format") or {}).get("protocol") or "").startswith(("ctr-", "cbc-"))
            for t in ((info or {}).get("media") or {}).get("transcodings") or [] if isinstance(t, dict))
        return super()._extract_info_dict(info, *args, **kwargs)


def entry_to_candidate(source: str, entry: dict) -> Candidate | None:
    url = entry.get("webpage_url") or entry.get("url")
    if not url or not entry.get("id"):
        return None
    artist = " ".join(str(x) for x in (
        entry.get("artist"), " ".join(entry.get("artists") or []), entry.get("uploader"), entry.get("channel"),
    ) if x)
    duration = entry.get("duration")
    return Candidate(source, str(entry["id"]), entry.get("title") or "", artist,
                     float(duration) if duration else None, url=url)


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def free_download(raw: dict) -> dict | None:
    """The artist's free download of one SoundCloud track (SoundCloud's API answer), or None. `direct`: SoundCloud's
    own download button, which yt-dlp can fetch; otherwise a gate page only the user can go through."""
    page = raw.get("permalink_url")
    common = {"page": page, "title": raw.get("title") or "", "uploader": (raw.get("user") or {}).get("username") or ""}
    if page and raw.get("downloadable") and raw.get("has_downloads_left"):
        return {"url": page, "host": "soundcloud.com", "direct": True, **common}
    url = raw.get("purchase_url")
    if not url or not url.startswith(("http://", "https://")):
        return None
    host = _host(url)
    gate = any(host == h or host.endswith("." + h) for h in GATE_HOSTS)
    if gate or "free" in (raw.get("purchase_title") or "").lower():
        return {"url": url, "host": host, "direct": False, **common}
    return None


def stream_url(source: str, source_id: str | None) -> str | None:
    if not source_id:
        return None
    if source == "youtube_music":
        return f"https://music.youtube.com/watch?v={source_id}"
    if source == "youtube":
        return f"https://www.youtube.com/watch?v={source_id}"
    if source == "soundcloud":
        return f"https://api.soundcloud.com/tracks/{source_id}"
    return None


class _Logger:
    """yt-dlp writes errors to stderr even with quiet=True; route everything into debug events instead."""

    def __init__(self, emit: Emit):
        self.emit = emit

    def debug(self, msg: str) -> None:
        self.emit(Message("debug", f"yt-dlp: {msg}"))

    info = warning = error = debug


class FallbackSource:
    def __init__(self, verbose: bool = False, emit: Emit = no_emit, check: Callable[[], None] = lambda: None,
                 logins: Mapping[str, tuple[str, str | None]] | None = None):
        self.emit = emit
        self.check = check  # raises events.Cancelled once Stop was pressed; called before every request
        self.opts = {"quiet": True, "no_warnings": not verbose, "noprogress": True, "logger": _Logger(emit)}
        # account service -> (browser, profile); only for format listings and downloads
        self.logins = dict(logins or {})

    def _extract(self, url: str, flat: bool) -> dict:
        opts = {**self.opts, "skip_download": True}
        if flat:
            opts["extract_flat"] = "in_playlist"
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def queries(self, track: SourceTrack) -> list[tuple[str, str, int]]:
        q = f"{track.first_artist} {track.title}"
        out = []
        if track.isrc:
            out.append(("youtube_music", f"{YTM_SEARCH}{quote_plus(track.isrc)}#songs", 3))
        out += [
            ("youtube_music", f"{YTM_SEARCH}{quote_plus(q)}#songs", 3),
            ("soundcloud", f"scsearch5:{q}", 5),
            ("youtube", f"ytsearch5:{track.first_artist} - {track.title}", 5),
        ]
        return out

    def search(self, track: SourceTrack, sources: tuple[str, ...] | None = None) -> tuple[list[Candidate], list[str]]:
        """All searches at once (each takes seconds), then the missing lengths at once; results keep the order of
        queries(). A DRM-protected upload is left out: it can never be used. `sources`: only these."""
        queries = [q for q in self.queries(track) if sources is None or q[0] in sources]
        errors: list[str] = []

        def run(q: tuple[str, str, int]) -> dict | Exception:
            source, url, _ = q
            self.emit(Message("debug", f"{SOURCE_NAMES[source]} search: {url}"))
            try:
                return self._extract(url, flat=True)
            except Exception as e:  # yt-dlp raises many types; any of them means "this source failed"
                return e

        self.check()  # Stop: before the searches go out, after them, and before every length lookup
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            infos = list(pool.map(run, queries))
        self.check()
        found: list[Candidate] = []
        seen: set[str] = set()
        for (source, _, limit), info in zip(queries, infos):
            if isinstance(info, Exception):
                errors.append(f"{SOURCE_NAMES[source]} search failed: {short_error(info)}")
                continue
            for entry in list(info.get("entries") or [])[:limit]:
                c = entry_to_candidate(source, entry)
                if c is None or c.url in seen:
                    continue
                seen.add(c.url)
                found.append(c)

        def complete(c: Candidate) -> Candidate | None:
            if c.duration_s is not None:
                return c
            self.check()
            try:
                return entry_to_candidate(c.source, self._extract(c.url, flat=False)) or c
            except Exception as e:
                if drm_protected(e):
                    return None
                # stays without a duration and cannot match; may be a network drop, so it is an error (tried
                # again next run), not "not found"
                errors.append(f"{SOURCE_NAMES[c.source]} lookup of {c.url} failed: {short_error(e)}")
                return c

        missing = sum(1 for c in found if c.duration_s is None)
        with ThreadPoolExecutor(max_workers=max(1, min(8, missing))) as pool:
            done = list(pool.map(complete, found))
        return [c for c in done if c is not None], errors

    def _soundcloud_track(self, url: str) -> dict:
        """SoundCloud's own answer for one track: yt-dlp leaves out the download and "buy" fields, so this asks the
        API through yt-dlp's SoundCloud client (which keeps its access key up to date)."""
        with yt_dlp.YoutubeDL(self.opts) as ydl:
            ie = ydl.get_info_extractor("Soundcloud")
            ie.initialize()
            return ie._call_api(ie._resolv_url(url), None, headers=ie._HEADERS) or {}

    def free_downloads(self, cands: list[Candidate]) -> list[dict]:
        """The artists' free downloads behind these SoundCloud versions, each with the `key` of its version. A failed
        lookup only costs that link (a debug line), never the track."""
        out = []
        for c in cands:
            if c.source != "soundcloud" or not c.url:
                continue
            self.check()
            try:
                found = free_download(self._soundcloud_track(c.url))
            except Exception as e:
                self.emit(Message("debug", f"SoundCloud download info for {c.url} failed: {short_error(e)}"))
                continue
            if found:
                out.append({**found, "key": c.key})
        return out

    def _login(self, source: str, account: bool) -> dict:
        service = ACCOUNT_OF.get(source)
        if not account or service not in self.logins:
            return {}
        return ytdlp_login(service, *self.logins[service])

    def stream_kbps(self, source: str, source_id: str, account: bool = False) -> int | None:
        """The bitrate of the stream a download takes (the format download() picks), read without downloading:
        before an account download (does the login give ~256 kbps for this track?), and for files downloaded before
        Discjockey kept it. None for a source it can't ask. Through a SoundCloud login, a Go+ stream that exists only
        DRM-protected raises a "DRM protected" error (drm_protected), as yt-dlp does when every stream is protected."""
        url = stream_url(source, source_id)
        if url is None:
            return None
        self.check()
        login = self._login(source, account)
        opts = {**self.opts, **login, "skip_download": True, "format": "bestaudio/best"}
        sc = SoundcloudDrmIE() if source == "soundcloud" and login else None
        with yt_dlp.YoutubeDL(opts) as ydl:
            if sc:
                ydl.add_info_extractor(sc)
            info = ydl.extract_info(url, download=False) or {}
        rate = info.get("abr") or info.get("tbr")
        kbps = round(rate) if rate else None
        if sc and sc.drm_premium and (kbps or 0) < PREMIUM_MIN_KBPS:  # not "no Go+ stream": the account isn't at fault
            raise RuntimeError(f"[soundcloud] {source_id}: the Go+ stream is DRM protected")
        return kbps

    def _browser_cookies(self, browser: str, profile: str | None = None):
        return yt_dlp.cookies.extract_cookies_from_browser(browser, profile)

    def check_account(self, service: str, browser: str, profile: str | None = None) -> dict:
        """Setup's "Check": can yt-dlp read the login from this browser, and does the account give ~256 kbps? Looks
        only at the names of the browser's cookies; a cookie value is never shown or kept. A song whose stream is
        DRM-protected is passed over."""
        def answer(ok: bool, problem: str | None, kbps: int | None = None, detail: str = "") -> dict:
            return {"ok": ok, "problem": problem, "kbps": kbps, "detail": detail}

        try:
            jar = self._browser_cookies(browser, profile)
        except Exception as e:
            return answer(False, "cookies_unreadable", detail=short_error(e))
        domain, names = LOGIN_COOKIES[service]
        if not any(c.name in names and c.domain.endswith(domain) for c in jar):
            return answer(False, "not_logged_in")
        source, best = CHECK_SOURCE[service], 0
        login, self.logins = self.logins, {**self.logins, service: (browser, profile)}
        try:
            entries = list(self._extract(CHECK_QUERY[service], flat=True).get("entries") or [])[:3]
            for entry in entries:
                c = entry_to_candidate(source, entry)
                if c is not None:
                    try:
                        best = max(best, self.stream_kbps(source, c.id, account=True) or 0)
                    except Exception as e:
                        if not drm_protected(e):
                            raise
                        continue  # says nothing about the account: the next song is checked
                if best >= PREMIUM_MIN_KBPS:
                    break
        except Exception as e:
            unreadable = signal_of(e) == "cookies_unreadable"
            return answer(False, "cookies_unreadable" if unreadable else "failed", detail=short_error(e))
        finally:
            self.logins = login
        if best < PREMIUM_MIN_KBPS:
            return answer(False, "no_premium", best or None)
        return answer(True, None, best)

    def lookup(self, source: str, url: str) -> Candidate | None:
        """One link the user pasted: its id, title and length, without downloading."""
        self.check()
        return entry_to_candidate(source, self._extract(url, flat=False))

    def download(self, cand: Candidate, workdir: Path,
                 progress: Callable[[int, int | None], None] | None = None,
                 section: tuple[float, float] | None = None, account: bool = False) -> Path:
        """section=(start, end) in seconds: only that part (the previews in the hub's "Wrong song?" dialog).
        A `direct` candidate takes only the artist's original file from SoundCloud's download button."""
        def hook(d: dict) -> None:  # an exception here (Stop pressed) aborts the download
            if progress and d.get("status") == "downloading":
                progress(d.get("downloaded_bytes") or 0, d.get("total_bytes") or d.get("total_bytes_estimate"))

        # A section is cut by ffmpeg, which is handed the manifest for a DASH format, and the app's ffmpeg has no dash
        # demuxer (no libxml2): DASH formats come last for a section. Full downloads fetch DASH segments themselves.
        audio_format = SECTION_FORMAT if section else "bestaudio/best"
        opts = {**self.opts, **self._login(cand.source, account),
                "format": "download" if cand.direct else audio_format, "noplaylist": True,
                "progress_hooks": [hook],
                "outtmpl": str(workdir / f"{cand.source}_%(id)s.%(ext)s")}
        if section:
            opts["download_ranges"] = download_range_func(None, [section])
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(cand.url, download=True)
            except Exception as e:
                if drm_protected(e):
                    raise Protected(f"{SOURCE_NAMES[cand.source]} marks this upload as DRM-protected, so Discjockey can't "
                                    "play or use it. Pick another version.") from None
                raise
            path = Path(ydl.prepare_filename(info))
        if path.exists():
            return path
        files = [p for p in sorted(workdir.glob(f"{cand.source}_*")) if p.suffix not in (".part", ".aiff")]
        if files:
            return files[0]
        raise RuntimeError("yt-dlp finished but no file was found")
