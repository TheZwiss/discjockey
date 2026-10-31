"""One track: Qobuz (the exact id, by ISRC, by name) -> the playlist's own upload -> the fallback search, each download
checked, converted and judged."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from . import audio, quality
from .accounts import ACCOUNT_KBPS, ACCOUNT_OF, PREMIUM_MIN_KBPS, signal_of, stream_rank, tier
from .events import AccountUsage, Checked, Emit, Message, SourceChosen, Tracker, no_emit, null_tracker
from .fallback import drm_protected, short_error, stream_url
from .matching import duration_ok, fallback_match, isrc_match, qobuz_match, rank
from .models import Candidate, SourceTrack

QOBUZ_TRIES_PER_STEP = 2
MAX_FALLBACK_DOWNLOADS = 3
GIVE_UP_AFTER = 5  # tracks in a row without a ~256 kbps stream: that account is not asked again in this run
MISSES_PER_TRACK = 2  # format listings without a ~256 kbps stream per account service and track; then no more


@dataclass
class Ready:
    path: Path  # converted, tagged AIFF in .tmp/
    status: str
    source: str
    source_id: str
    source_format: str
    cutoff_hz: int | None
    comment: str
    kbps: int | None = None  # lossy sources only


@dataclass
class AcquireResult:
    kind: str  # ready | missing | errored | queued
    ready: Ready | None = None
    rejected: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = ""  # why it was queued
    free_downloads: list[dict] | None = None  # the artists' free downloads (SoundCloud); None: not looked
    qobuz_searched: bool = False  # every Qobuz search of this track ran without an error


def make_ready(downloaded: Path, track: SourceTrack, cand: Candidate, workdir: Path,
               tracker: Tracker | None = None) -> Ready | None:
    """Duration check, convert, analyse, tag. None if the file is not the track (e.g. a 30 s preview)."""
    tracker = tracker or null_tracker()
    tracker.step("check")
    info = quality.probe(downloaded)
    ok = duration_ok(track, info.duration_s)
    tracker.emit(Checked(tracker.track_id, info.duration_s, track.duration_ms / 1000, info.codec, ok))
    if not ok:
        return None
    tracker.step("convert")
    out = workdir / f"{cand.source}_{cand.id}.aiff"
    audio.convert_to_aiff(downloaded, out, duration_s=info.duration_s,
                          progress=lambda done, total: tracker.progress(done, total, "seconds"))
    tracker.step("analyse")
    lossless_codec = quality.is_lossless_codec(info.codec)
    cutoff = quality.analyze(out, lossy=not lossless_codec)
    status = quality.verdict(lossless_codec, cutoff)
    kbps = None if lossless_codec else info.kbps
    comment = quality.quality_line(cand.source, info.codec, status, cutoff, kbps)
    # a YouTube Music or SoundCloud track has no album mostly; a Qobuz match knows it (stage 6 D10)
    audio.write_tags(out, title=track.title, artists=track.artists, album=track.album or cand.album or "",
                     isrc=track.isrc, label=cand.label, cover=audio.fetch_cover(cand.image_url or track.image_url),
                     comment=comment)
    return Ready(out, status, cand.source, cand.id, info.codec, cutoff, comment, kbps)


@dataclass
class _Tries:
    """One track's downloads over the upload step and the fallback chain, so that the pause between two downloads and
    MISSES_PER_TRACK hold across both."""
    attempts: int = 0  # downloads started for this track outside Qobuz: the next one gets the fallback pause
    missed: dict = field(default_factory=dict)  # account service -> format listings without ~256 kbps (this track)
    streams: int = 0  # stream downloads started for this track (MAX_FALLBACK_DOWNLOADS holds across upload and search)


def upload_candidate(upload: SourceTrack) -> Candidate:
    """The playlist's own upload as a candidate (stage 6 I6): its service and id are the candidate's (D1). The download
    address comes from the id, never from the track's page link."""
    return Candidate(upload.service, upload.id, upload.title, " ".join(upload.artists), upload.duration_ms / 1000,
                     url=stream_url(upload.service, upload.id), album=upload.album or None,
                     image_url=upload.image_url)


def _with_twins(keys: set[str]) -> set[str]:
    """YouTube Music's upload `youtube_music:X` and the search's `youtube:X` are the same video: what is skipped or
    rejected under one name stays out under the other too."""
    out = set(keys)
    for key in keys:
        source, _, vid = key.partition(":")
        if source == "youtube_music":
            out.add(f"youtube:{vid}")
        elif source == "youtube":
            out.add(f"youtube_music:{vid}")
    return out


def _offers(offers: list[dict]) -> list[dict]:
    return [{k: v for k, v in o.items() if k != "key"} for o in offers]


@dataclass
class Acquirer:
    qobuz: Any | None
    fallback: Any | None
    budget: Any
    pacer: Any
    process: Callable[..., Ready | None]  # (downloaded, track, cand, workdir, tracker) -> Ready | None
    emit: Emit = no_emit
    accounts: dict = field(default_factory=dict)  # service -> Budget, for each account service that is set up
    account_downloaded: set = field(default_factory=set, init=False)  # a logged-in request was made: pause first
    misses: dict = field(default_factory=dict, init=False)  # service -> tracks in a row without a ~256 kbps stream
    given_up: set = field(default_factory=set, init=False)  # services not asked again in this run (GIVE_UP_AFTER)
    qobuz_downloaded: bool = field(default=False, init=False)  # a protection pause is due before the next one
    qobuz_trouble: bool = field(default=False, init=False)  # a Qobuz request failed for the current track

    def _debug(self, text: str) -> None:
        self.emit(Message("debug", text))

    def _qobuz_failed(self, message: str, kind: str) -> None:
        was_stopped = self.budget.stopped
        self.qobuz_trouble = True
        self.budget.failed(message, kind)
        if self.budget.stopped and not was_stopped:
            self.emit(Message("warning", "Qobuz failed several times in a row, so it is paused for the rest of "
                                         "this run. The remaining tracks wait for the next run."))

    def acquire(self, track: SourceTrack, rejected: set[str], workdir: Path, lossless_only: bool,
                tracker: Tracker | None = None, better_than: int | None = None, originals: bool = True,
                declined: set[str] | frozenset[str] = frozenset(), qobuz: bool = True,
                exact: str | None = None, upload: SourceTrack | None = None) -> AcquireResult:
        """`better_than`: an upgrade check of a lossy file with that bitrate; below ~256 kbps the accounts are asked
        too (spec §4), and only a clearly better stream counts. `originals` False: an upgrade check that leaves out
        the artists' originals on SoundCloud, already searched since the last real check (free_downloads stays None).
        `qobuz` False: likewise without the Qobuz search (qobuz_searched stays False).
        `declined`: streams of the current upload not offered again (state's declined_streams); only the accounts' step
        skips them, the artist's original of the same upload is still tried.
        `upload`: the playlist's own SoundCloud / YouTube Music track (stage 6 D7), tried once right after Qobuz and
        before the fallback search (_upload); an upgrade check takes its original and its account stream first."""
        tracker = tracker or null_tracker()
        res = AcquireResult("missing")
        skip = _with_twins(set(rejected))
        self.qobuz_trouble = False

        if self.qobuz is not None and qobuz:
            if self.budget.exhausted():
                return AcquireResult("queued", note=self.budget.why_exhausted())
            if exact:  # the playlist read has the facts already: no metadata request, the download is paced and counted
                c = Candidate("qobuz", exact, track.title, " ".join(track.artists), track.duration_ms / 1000,
                              isrc=track.isrc, album=track.album, image_url=track.image_url)
                if c.key not in skip:
                    ready = self._try(c, track, workdir, res, skip, lossless_only, tracker, qobuz=True, how="exact")
                    if ready:
                        res.kind, res.ready = "ready", ready
                        return res
                    skip.add(c.key)  # the ISRC search that follows doesn't download the same id again
            steps = []
            if track.isrc:
                steps.append(("ISRC", track.isrc, lambda c: isrc_match(track, c, skip)))
            steps.append(("name", f"{track.first_artist} {track.title}", lambda c: qobuz_match(track, c, skip)))
            how = {"ISRC": "isrc", "name": "name"}
            searched = 0
            for label, query, accept in steps:
                if self.budget.stopped:  # paused by the auto-stop during this track: no further Qobuz requests
                    break
                tracker.step("search")
                try:
                    self.pacer.before_qobuz_search()
                    cands = self.qobuz.search(query, limit=10)
                except Exception as e:
                    res.errors.append(f"Qobuz search by {label} failed: {e}")
                    self._qobuz_failed(f"{track.first_artist} - {track.title}: search failed ({e})", "search_failed")
                    continue
                searched += 1
                self.budget.succeeded()
                self._debug(f"Qobuz search by {label}: {query} -> {len(cands)} results")
                for c in cands:
                    self._debug(f"  {c.key}  {c.artist} - {c.title}  ({c.duration_s} s)")
                for c in rank(track, [c for c in cands if accept(c)])[:QOBUZ_TRIES_PER_STEP]:
                    if c.key in skip:
                        continue
                    if self.budget.stopped:
                        break
                    if self.budget.exhausted():
                        res.kind, res.note = "queued", self.budget.why_exhausted()
                        return res
                    ready = self._try(c, track, workdir, res, skip, lossless_only, tracker, qobuz=True,
                                      how=how[label])
                    if ready:
                        res.kind, res.ready = "ready", ready
                        return res
            # Qobuz has nothing better: an upgrade check that waits for an account needn't ask again (execute.py)
            res.qobuz_searched = searched == len(steps) and not self.qobuz_trouble

        if self.fallback is None or (lossless_only and self.qobuz_trouble):
            res.kind = "errored" if res.errors else "missing"
            return res
        up = upload_candidate(upload) if upload is not None else None
        tries = _Tries()
        if lossless_only:
            # an upgrade check: SoundCloud only, for the artists' free downloads (a direct one may be lossless)
            found: dict = {}
            ready = (self._fallback(track, workdir, res, skip, True, tracker, sources=("soundcloud",), found=found,
                                    tries=tries, upload=up)
                     if originals else None)
            waiting = set()  # accounts that could give ~256 kbps but can't be asked today: the check waits for them
            if ready is None and better_than is not None and better_than < PREMIUM_MIN_KBPS:
                waiting = self._possible() - self._usable()
                if self._usable():
                    ready = self._better_stream(track, workdir, res, skip | set(declined), tracker, better_than, found,
                                                tries=tries, upload=up)
            if ready:
                res.kind, res.ready = "ready", ready
                return res
            if waiting:  # like Qobuz at its limit: not "checked, nothing yet", which would skip it for a week
                res.kind, res.note = "queued", self.accounts[min(waiting)].why_exhausted()
                return res
            res.kind = "errored" if res.errors else "missing"
            return res
        if self.qobuz_trouble:
            # Qobuz itself had a problem, so we don't know that it lacks the track: try again next run instead
            # of filling the library with lossy copies that would each need an upgrade later.
            res.kind = "errored"
            return res

        ready = None
        if up is not None and up.key not in skip:  # rejected before ("Wrong song?", a failed check): not tried
            ready = self._upload(track, up, upload.account_only, workdir, res, skip, tracker, tries)
            skip |= _with_twins({up.key})  # tried once: the search that follows doesn't download it again
        if ready is None and res.kind != "queued":
            ready = self._fallback(track, workdir, res, skip, False, tracker, tries=tries)
        if res.kind == "queued":
            return res
        if ready:
            res.kind, res.ready = "ready", ready
            return res
        res.kind = "errored" if res.errors else "missing"
        return res

    def _possible(self) -> set[str]:
        """Account services that can give ~256 kbps in this run: set up, and not given up on (GIVE_UP_AFTER)."""
        return set(self.accounts) - self.given_up

    def _usable(self) -> set[str]:
        """Account services that can download right now: possible, today's limit not used up, not paused."""
        return {s for s in self._possible() if not self.accounts[s].exhausted()}

    def _waits(self, matches: list[Candidate], usable: set[str], demoted: set[str] | frozenset[str] = frozenset()
               ) -> str | None:
        """§4: why the track waits for the next sync. That is when its best match needs an account that is used up
        or paused today, and no other match of the same or a better tier can come now. A demoted match showed no
        ~256 kbps stream through its account, so it only counts as a free one."""
        if not matches:
            return None

        def rank(c: Candidate, services: set[str]) -> int:
            return stream_rank(c.source, set() if c.key in demoted else services)

        possible = self._possible()
        now = min(tier(rank(c, usable)) for c in matches)
        best = min(matches, key=lambda c: rank(c, possible))
        if tier(rank(best, possible)) < now:
            return self.accounts[ACCOUNT_OF[best.source]].why_exhausted()
        return None

    def _account_failed(self, service: str, message: str, kind: str) -> None:
        budget = self.accounts[service]
        was_stopped = budget.stopped
        budget.failed(message, kind)
        if budget.stopped and not was_stopped:
            self.emit(Message("warning", f"{budget.name} failed several times in a row, so it is paused for the rest "
                                         "of this run. Tracks that need it wait for the next run."))

    def premium(self, c: Candidate, service: str, track: SourceTrack, first: bool = True) -> bool | None:
        """§4: the stream's bitrate through the login, read before the download. False means no ~256 kbps stream
        for this version (or a DRM-protected one); it is then tried as a free one. None: the listing itself failed
        (timeout, 5xx, unreadable login), which says nothing about the stream: falsy like False, but never
        remembered against the version. A warning sign counts toward the account's auto-stop; a
        missing premium stream only once per track (`first`), since one song's other uploads say nothing new."""
        budget = self.accounts[service]
        who = f"{track.first_artist} - {track.title}"
        try:
            kbps = self.fallback.stream_kbps(c.source, c.id, account=True)
        except Exception as e:  # yt-dlp raises many types
            text = short_error(e)
            if drm_protected(e):  # never worked around, and not the account's fault
                self._debug(f"{c.key}: the {budget.name} stream is DRM-protected, so Discjockey doesn't use it")
            elif signal_of(e):
                self._account_failed(service, f"{who}: {text}", signal_of(e))
            else:
                self._debug(f"{c.key}: {budget.name} formats not read: {text}")
            return False if drm_protected(e) else None
        if kbps and kbps >= PREMIUM_MIN_KBPS:
            budget.succeeded()
            self.misses[service] = 0
            return True
        message = f"{who}: no ~{ACCOUNT_KBPS} kbps stream through your account ({kbps or '?'} kbps)"
        if not first:
            budget.note("premium_missing", message)
            return False
        if service == "youtube":
            self._account_failed(service, message, "premium_missing")
        else:  # many SoundCloud uploads have no Go+ stream at all, so one missing one says little
            budget.note("premium_missing", message)
        self.misses[service] = self.misses.get(service, 0) + 1
        if self.misses[service] >= GIVE_UP_AFTER and service not in self.given_up:
            self.given_up.add(service)
            self.emit(Message("info", f"{budget.name} gave no ~{ACCOUNT_KBPS} kbps stream for {GIVE_UP_AFTER} tracks "
                                      "in a row, so Discjockey doesn't ask it again in this run. Those tracks come from "
                                      "the free sources."))
        return False

    def _upload(self, track: SourceTrack, c: Candidate, account_only: bool, workdir: Path, res: AcquireResult,
                skip: set[str], tracker: Tracker, tries: _Tries) -> Ready | None:
        """The playlist's own upload (stage 6 D7, I6), before the fallback search: on SoundCloud the artist's free
        download first (every offer, gate links too, is noted), then its stream through _streams, with the account
        rules of any other match (listing, pacing, limits, the §4 wait). It isn't run through fallback_match (it is
        the song's own upload), but make_ready's length check still applies. `account_only` (SoundCloud Go+ only):
        never downloaded without the account, whose free stream is a 30 s preview."""
        spare = None
        if c.source == "soundcloud":
            offers = self.fallback.free_downloads([c])
            if offers:
                res.free_downloads = _offers(offers)
            if any(o["direct"] for o in offers):
                tries.attempts += 1
                ready = self._try(replace(c, direct=True), track, workdir, res, skip, False, tracker, qobuz=False,
                                  how="upload")
                if ready is not None:
                    if (ready.status == "lossless" or not ready.kbps or ready.kbps >= ACCOUNT_KBPS
                            or ACCOUNT_OF[c.source] not in self._possible()):
                        return ready
                    spare = ready  # below the account tier: kept in case the upload's account stream beats it
        return self._streams(track, [c], workdir, res, skip, tracker, tries, spare=spare, how="upload",
                             account_only={c.key} if account_only else frozenset())

    def _fallback(self, track: SourceTrack, workdir: Path, res: AcquireResult, skip: set[str], lossless_only: bool,
                  tracker: Tracker, sources: tuple[str, ...] | None = None, found: dict | None = None,
                  tries: _Tries | None = None, upload: Candidate | None = None) -> Ready | None:
        """Search, note the artists' free downloads, then download:
        - first an artist's original file from SoundCloud's download button;
        - then the best matches in the order of spec §2 (_streams): through an account when it gives ~256 kbps, else
          free.
        A track whose best match needs a used-up or paused account waits (res.kind "queued", §4). An upgrade check
        takes only the originals, and its search errors stay out of the result: the check simply found nothing.
        `found` (an upgrade check): gets the sources searched and their results ("cands"), so that the account streams
        don't search those sources again. `tries`: the track's downloads so far (the upload step's), for the pauses.
        `upload` (an upgrade check): the playlist's own upload, whose original joins the originals first."""
        tries = tries if tries is not None else _Tries()
        tracker.step("search")
        try:
            cands, errors = self.fallback.search(track, sources) if sources else self.fallback.search(track)
        except Exception as e:
            cands, errors = [], [f"Fallback search failed: {e}"]
        if found is not None:
            found.update(sources=sources, cands=cands)
        if lossless_only:
            for err in errors:
                self._debug(err)
        else:
            res.errors += errors
        usable = self._usable()
        matches = sorted((c for c in cands if fallback_match(track, c, skip)),
                         key=lambda c: (stream_rank(c.source, usable), abs(c.duration_s * 1000 - track.duration_ms)))
        self._debug(f"Fallback: {len(cands)} results, {len(matches)} match")
        for c in cands:
            self._debug(f"  {c.key}  {c.artist} - {c.title}  ({c.duration_s} s)")
        if (upload is not None and upload.key not in skip and (sources is None or upload.source in sources)):
            matches = [upload] + [c for c in matches if c.key != upload.key]
        offers = self.fallback.free_downloads([c for c in matches if c.source == "soundcloud"])
        if not errors or offers:  # a failed search says nothing about the links: keep the ones known
            noted = res.free_downloads or []  # the upload step's come first
            res.free_downloads = noted + [o for o in _offers(offers) if o not in noted]
        direct = {o["key"] for o in offers if o["direct"]}
        originals = [replace(c, direct=True) for c in matches if c.key in direct]
        wait = None if lossless_only else self._waits(matches, usable)
        if wait and not originals:
            res.kind, res.note = "queued", wait
            return None

        spare = None
        for c in originals:
            if tries.attempts:
                self.pacer.between_fallback_downloads()
            tries.attempts += 1
            how = "upload" if upload is not None and c.key == upload.key else "fallback"
            ready = self._try(c, track, workdir, res, skip, lossless_only, tracker, qobuz=False, how=how)
            if ready is None:
                continue
            if (lossless_only or ready.status == "lossless" or not ready.kbps or ready.kbps >= ACCOUNT_KBPS
                    or not (usable or wait)):
                return ready
            spare = ready  # a lossy original below the account tier (§2 "3½"): kept in case no stream beats it
        if lossless_only:
            return None
        if wait:  # only an original below the account tier came: the track still waits for the account
            res.kind, res.note = "queued", wait
            return None
        return self._streams(track, matches, workdir, res, skip, tracker, tries, spare=spare)

    def _streams(self, track: SourceTrack, matches: list[Candidate], workdir: Path, res: AcquireResult,
                 skip: set[str], tracker: Tracker, tries: _Tries, spare: Ready | None = None, how: str = "fallback",
                 account_only: set[str] | frozenset[str] = frozenset()) -> Ready | None:
        """The stream downloads of spec §2, best rank first, at most MAX_FALLBACK_DOWNLOADS per track
        (`tries.streams`, over the upload step and the search): through an account when
        its format listing shows ~256 kbps, else free. The listing is a logged-in request: it gets the protection
        pause, and an account service is listed at most MISSES_PER_TRACK times per track without a ~256 kbps stream
        (`tries.missed`, over the upload step and the search). A track whose best remaining match needs a used-up or
        paused account waits (res.kind "queued", §4). `spare`: an artist's original below the account tier, returned
        once only free streams are left. `account_only`: keys never downloaded without their account."""
        pending, demoted, failed = list(matches), set(), set()
        place = {c.key: i for i, c in enumerate(matches)}
        while pending and tries.streams < MAX_FALLBACK_DOWNLOADS:
            usable = self._usable()  # a limit can run out, or an account pause, during one track
            wait = self._waits(pending, usable, demoted)
            if wait:  # what's left is worse than what an account gives on another day
                res.kind, res.note = "queued", wait
                return None
            pending.sort(key=lambda x: (stream_rank(x.source, set() if x.key in demoted else usable),
                                        abs(x.duration_s * 1000 - track.duration_ms), place[x.key]))
            c = pending[0]
            service = ACCOUNT_OF.get(c.source)
            account = service in usable and c.key not in demoted
            if account and tries.missed.get(service, 0) >= MISSES_PER_TRACK:
                demoted.add(c.key)  # this song's uploads there have shown no ~256 kbps stream: no more listings
                continue
            if account:  # the format listing is a logged-in request too: it gets the protection pause
                if service in self.account_downloaded:
                    self.pacer.between_account_downloads(service)
                elif tries.attempts:
                    self.pacer.between_fallback_downloads()
                self.account_downloaded.add(service)
                listed = self.premium(c, service, track, first=not tries.missed.get(service))
                if not listed:
                    tries.missed[service] = tries.missed.get(service, 0) + 1
                    if listed is None:
                        failed.add(c.key)  # the listing failed: the version isn't known to lack the stream
                    demoted.add(c.key)  # tried later as a free stream, in its free rank
                    continue
            pending.pop(0)
            if not account and c.key in account_only:  # its free stream is only a preview
                self._debug(f"{c.key}: only the account plays all of it, so it isn't downloaded without the account")
                if c.key in demoted and c.key not in failed:  # its listing showed no ~256 kbps stream: rejected for good,
                    res.rejected.append(c.key)  # as its preview was (a failed listing, or a missing, paused or
                    # used-up account, is not that: not remembered)
                continue
            if spare is not None and not account:
                return spare  # what's left are free streams: the artist's own file is the better one
            if not account and tries.attempts:
                self.pacer.between_fallback_downloads()
            tries.attempts += 1
            tries.streams += 1
            ready = self._try(c, track, workdir, res, skip, False, tracker, qobuz=False, how=how,
                              account=service if account else None)
            if ready:
                return ready
        return spare

    def _better_stream(self, track: SourceTrack, workdir: Path, res: AcquireResult, skip: set[str],
                       tracker: Tracker, than: int, found: dict | None = None, tries: _Tries | None = None,
                       upload: Candidate | None = None) -> Ready | None:
        """An upgrade check of a lossy file below ~256 kbps (spec §4): the same track through an account, kept only
        when it is clearly better. Never a free stream. Search errors only go to the debug log (the check simply
        found nothing). Listings are paced and capped per service like a new download's (MISSES_PER_TRACK).
        `found`: what the originals' search (_fallback) already found; those sources aren't searched again. `tries`:
        the downloads of the originals' step, for the first listing's pause. `upload`: the playlist's own upload, asked
        first, before any search."""
        found = found or {}
        tries = tries if tries is not None else _Tries()
        state = {"downloads": 0}

        def attempt(c: Candidate) -> Ready | None:
            service = ACCOUNT_OF[c.source]
            if service not in self._usable() or tries.missed.get(service, 0) >= MISSES_PER_TRACK:
                return None
            if service in self.account_downloaded:  # the format listing is a logged-in request too
                self.pacer.between_account_downloads(service)
            elif tries.attempts:  # after a download from SoundCloud (an artist's original) or the other account
                self.pacer.between_fallback_downloads()
            self.account_downloaded.add(service)
            if not self.premium(c, service, track, first=not tries.missed.get(service)):
                tries.missed[service] = tries.missed.get(service, 0) + 1
                return None
            state["downloads"] += 1
            tries.attempts += 1
            how = "upload" if upload is not None and c.key == upload.key else "fallback"
            ready = self._try(c, track, workdir, res, skip, False, tracker, qobuz=False, how=how, account=service)
            if ready and ready.kbps and ready.kbps > than and ready.kbps >= PREMIUM_MIN_KBPS:
                return ready
            if ready:  # came out no better: never offered again for this track
                res.rejected.append(c.key)
                skip.add(c.key)
            return None

        if upload is not None and upload.key not in skip and ACCOUNT_OF.get(upload.source) in self._usable():
            ready = attempt(upload)
            skip.add(upload.key)  # asked once: not again among the search's matches
            if ready:
                return ready
        usable = self._usable()
        searched = found.get("sources") or ()
        sources = tuple(src for src, service in ACCOUNT_OF.items() if service in usable and src not in searched)
        cands = [c for c in found.get("cands") or [] if ACCOUNT_OF.get(c.source) in usable]
        if sources:
            tracker.step("search")
            try:
                more, errors = self.fallback.search(track, sources)
            except Exception as e:
                more, errors = [], [f"Fallback search failed: {e}"]
            cands += more
            for err in errors:
                self._debug(err)
        matches = sorted((c for c in cands if fallback_match(track, c, skip)),
                         key=lambda c: (stream_rank(c.source, usable), abs(c.duration_s * 1000 - track.duration_ms)))
        self._debug(f"Better stream: {len(cands)} results, {len(matches)} match")
        for c in matches:
            if state["downloads"] >= MAX_FALLBACK_DOWNLOADS:
                break
            ready = attempt(c)
            if ready:
                return ready
        return None

    def _try(self, c: Candidate, track: SourceTrack, workdir: Path, res: AcquireResult, skip: set[str],
             lossless_only: bool, tracker: Tracker, qobuz: bool, how: str,
             account: str | None = None) -> Ready | None:
        # first, so that the protection pause can already show where the next download comes from
        tracker.emit(SourceChosen(tracker.track_id, c.source, how, c.title, c.duration_s))
        if qobuz and self.qobuz_downloaded:
            self.pacer.between_qobuz_downloads()  # 20-60 s since the previous Qobuz download, before this one
        tracker.step("download")
        source = self.qobuz if qobuz else self.fallback
        try:
            if account:
                downloaded = self.fallback.download(c, workdir, account=True,
                                                    progress=lambda done, total: tracker.progress(done, total, "bytes"))
            else:
                downloaded = source.download(c, workdir,
                                             progress=lambda done, total: tracker.progress(done, total, "bytes"))
        except Exception as e:
            if c.direct:  # the download button can need a SoundCloud login; the stream is tried next
                self._debug(f"SoundCloud original of {c.id} not available: {e}")
                return None
            if getattr(e, "permanent", False):  # e.g. region-locked on Qobuz: never try this one again
                res.rejected.append(c.key)
                skip.add(c.key)
            else:
                res.errors.append(f"Download from {c.source} ({c.id}) failed: {e}")
                if qobuz:  # also a preview-only answer: usually the account, so it counts toward the auto-stop
                    self._qobuz_failed(f"{track.first_artist} - {track.title}: {e}",
                                       getattr(e, "signal", "download_rejected"))
                elif account:
                    text = short_error(e)
                    self._account_failed(account, f"{track.first_artist} - {track.title}: {text}",
                                         signal_of(e) or "download_rejected")
            if qobuz:
                self.qobuz_downloaded = True
            if account:
                self.account_downloaded.add(account)
            return None
        if qobuz:
            self.qobuz_downloaded = True
            self.budget.count()
            tracker.emit(AccountUsage("qobuz", self.budget.used_today(), self.budget.allowance()))
        if account:
            self.account_downloaded.add(account)
            budget = self.accounts[account]
            budget.count()
            tracker.emit(AccountUsage(account, budget.used_today(), budget.allowance()))
        try:
            ready = self.process(downloaded, track, c, workdir, tracker)
        except Exception as e:
            res.errors.append(f"Could not convert the {c.source} file: {e}")
            return None
        if ready is None and qobuz:  # a Qobuz file shorter/longer than the track: often a 30 s preview
            self.budget.note("duration_mismatch", f"{track.first_artist} - {track.title}: Qobuz file {c.id} "
                                                  "does not have the track's length")
        if ready is None or (lossless_only and ready.status != "lossless"):
            if ready is not None and c.direct:
                return None  # a lossy original (a 320 MP3) is still the better file for a new download
            res.rejected.append(c.key)
            skip.add(c.key)
            return None
        return ready
