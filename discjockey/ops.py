"""Single operations outside a sync, for the hub's to-do list (spec "hub", 6.7).

Every operation runs through `run_single`, while the caller holds the run lock:
  1. fresh state; interrupted steps are recovered first (and reported);
  2. the entry must still look as the window showed it (status, path, parked file), else nothing is done;
  3. the change itself, through library.run_op (crash-safe, never overwrites);
  4. not_lossless.md is rewritten and a line goes into reports/operations.jsonl.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError

from . import audio, library, quality, report as rep
from .accounts import ACCOUNT_OF, signal_of
from .acquire import Acquirer, make_ready
from .candidates import current_key, mark_protected
from .events import AccountUsage, CancelToken, Emit, Result, SourceChosen, Tracker, no_emit
from .execute import Executor
from .fallback import short_error
from .library import NameReserver, Paths, delete_parked, full_fsync, run_op
from .models import Action, Candidate, Protected, SourceTrack, split_token
from .names import expected_stem, split_name, strip_id_suffix
from .pacing import NoPacer
from .planner import replacement_dir, superseded_dir

CURRENT_VERSION = "This is the version you have now."
NOT_THERE = ("Your current file is not where Discjockey expects it. Run a sync first, so it can find the file "
             "again.")
CHANGED = "This track changed in the meantime, so nothing was done. The page shows it as it is now."
NOT_LOSSLESS_YET = ("missing", "not_lossless", "fake_lossless")
BOUGHT_FORMATS = (".wav", ".aiff", ".aif", ".flac", ".mp3")  # an MP3: the artist's free download (often 320 kbps)
TO_AIFF = (".flac", ".mp3")
QOBUZ_PAUSED = ("Not downloaded: Qobuz is paused, because several Qobuz requests in a row failed (a warning sign for "
                "the account). Discjockey sends Qobuz nothing more until the next sync starts. A YouTube Music or "
                "SoundCloud version still works.")
NO_ACCESS = ("macOS didn't let Discjockey read this file. Move it to Downloads, or allow access in System Settings → "
             "Privacy & Security → Files and Folders.")


class OpProblem(Exception):
    """The operation was not done; the message is for the user. kind: changed | refused | failed."""

    def __init__(self, message: str, kind: str = "refused"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Done:
    result: Result
    recovered: list[tuple[str, bool]]  # interrupted steps finished first: (message, ok)


def snapshot(entry: dict | None) -> dict | None:
    """What the window showed of an entry; an operation is only done while the entry still looks like this."""
    if entry is None:
        return None
    return {"status": entry.get("status"), "path": entry.get("path"),
            "upgrade_file": (entry.get("upgrade") or {}).get("file")}


def log_operation(paths: Paths, now: datetime, track_id: str, entry: dict | None, operation: str, result: str,
                  message: str) -> None:
    paths.reports.mkdir(parents=True, exist_ok=True)
    line = {"time": now.isoformat(timespec="seconds"), "track_id": track_id,
            "artist": (entry or {}).get("artist"), "title": (entry or {}).get("title"),
            "operation": operation, "result": result, "message": message}
    with open(paths.operations_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def run_single(paths: Paths, operation: str, track_id: str, expect: dict | None,
               do: Callable[[dict], Result], now: Callable[[], datetime] = datetime.now) -> Done:
    """Runs `do(state)` as described in the module docstring. The caller holds library.run_lock."""
    state = library.open_state(paths)
    recovered = library.recover_pending(paths, state)
    library.clear_tmp(paths, state)
    entry = state["tracks"].get(track_id)
    try:
        if entry is None or snapshot(entry) != expect:
            raise OpProblem(CHANGED, "changed")
        result = do(state)
    except OpProblem as p:
        log_operation(paths, now(), track_id, entry, operation, p.kind, str(p))
        raise
    except Exception as e:
        log_operation(paths, now(), track_id, entry, operation, "failed", f"{type(e).__name__}: {e}")
        raise
    finally:
        rep.write_not_lossless(paths, state)
    log_operation(paths, now(), track_id, entry, operation, "done", result.note)
    return Done(result, recovered)


def _result(section: str, track_id: str, e: dict, note: str, **fields) -> Result:
    return Result(section, e["folder"], e["artist"], e["title"], track_id, note, **fields)


def set_hidden(paths: Paths, state: dict, track_id: str, hidden: bool) -> Result:
    """"Good enough, hide": the to-do list leaves the track out. Weekly upgrade checks go on."""
    e = state["tracks"][track_id]
    state["tracks"][track_id] = {**e, "hidden": bool(hidden)}
    library.save_state(paths, state)
    if hidden:
        return _result("hidden", track_id, e, "hidden from the to-do list")
    return _result("unhidden", track_id, e, "back on the to-do list")


def track_of(track_id: str, e: dict) -> SourceTrack:
    """The playlist side of an entry (its song key names the service), as far as the records know it (for actions run
    outside a sync)."""
    service, bare_id = split_token(track_id)
    return SourceTrack(bare_id, e["title"], (e["artist"],), "", None, e["duration_ms"], e.get("isrc"), service)


def _copy_synced(src: Path, dst: Path) -> None:
    try:
        fin = open(src, "rb")
    except PermissionError:
        raise OpProblem(NO_ACCESS) from None
    with fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)
        fout.flush()
        full_fsync(fout.fileno())


def _flac_to_aiff(flac: Path, aiff: Path, e: dict) -> None:
    """A bought FLAC becomes AIFF like everything else in the library, keeping its title, artists, album and cover."""
    audio.convert_to_aiff(flac, aiff)
    tags = FLAC(str(flac))

    def first(key: str) -> str | None:
        return (tags.get(key) or [None])[0]

    cover = next((p.data for p in tags.pictures if p.mime == "image/jpeg"), None)
    audio.write_tags(aiff, title=first("title") or e["title"], artists=tuple(tags.get("artist") or [e["artist"]]),
                     album=first("album") or "", isrc=first("isrc"), label=first("organization") or first("label"),
                     cover=cover, comment="bought file (FLAC)")


def _mp3_to_aiff(mp3: Path, aiff: Path, e: dict) -> None:
    """An MP3 (an artist's free download) becomes AIFF too, with the track's names and the MP3's cover."""
    audio.convert_to_aiff(mp3, aiff)
    try:
        tags = ID3(str(mp3))
    except ID3NoHeaderError:
        tags = None
    cover = next((f.data for f in tags.getall("APIC") if f.mime == "image/jpeg"), None) if tags else None
    album = str(tags["TALB"]) if tags and "TALB" in tags else ""
    audio.write_tags(aiff, title=e["title"], artists=(e["artist"],), album=album, isrc=e.get("isrc"), label=None,
                     cover=cover, comment="bought file (MP3)")


def add_bought_file(paths: Paths, state: dict, track_id: str, src: Path, *,
                    analyze: Callable[[Path], tuple[str, int | None]] = quality.inspect,
                    now: Callable[[], datetime] = datetime.now) -> Result:
    """A file the user bought, dropped into the window. Copied (never moved or changed) into .tmp/<track_id>/, FLAC
    and MP3 turned into AIFF there (an MP3 is judged before, so it stays lossy), then placed under the expected name
    where a lossless replacement of the current file goes (`replacement_dir`: next to it, out of a playlist folder's
    not_lossless/; without a file Library/<Folder>/) through run_op (refused if that name is taken) and adopted like a
    bought file the user put there by hand."""
    e = state["tracks"][track_id]
    if e["status"] not in NOT_LOSSLESS_YET:
        raise OpProblem("This track is lossless already, so it needs no bought file.")
    ext = src.suffix.lower()
    if ext not in BOUGHT_FORMATS:
        raise OpProblem("Only WAV, AIFF, FLAC or MP3 files can be added.")
    if not src.is_file():
        raise OpProblem("That file is not there any more.")
    name = f"{expected_stem(e['artist'], e['title'])}{'.aiff' if ext in TO_AIFF else ext}"
    dest = f"{replacement_dir(e, 'lossless')}/{name}"  # the planner looks there too, should a crash come next
    taken = OpProblem(f"{dest} is already taken by another file. Move or rename that file first.")
    if NameReserver(paths.root, state).is_taken(dest):
        raise taken
    workdir = paths.tmp / track_id
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        staged = workdir / f"bought{ext}"
        _copy_synced(src, staged)
        try:
            found = None
            if ext == ".mp3":  # judged as the MP3 it is: after the conversion it would look like PCM
                found = analyze(staged)
                mp3, staged = staged, workdir / "bought.aiff"
                _mp3_to_aiff(mp3, staged, e)
            if ext == ".flac":
                flac, staged = staged, workdir / "bought.aiff"
                _flac_to_aiff(flac, staged, e)
            found = found or analyze(staged)  # before anything is placed: a file without audio stays out
        except OpProblem:
            raise
        except Exception as err:
            raise OpProblem(f"Discjockey could not use this file ({err}).") from None
        try:
            run_op(paths, state, track_id, [(staged.relative_to(paths.root).as_posix(), dest)], None)
        except FileExistsError:  # a file with that name appeared meanwhile: it is left alone
            raise taken from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    # from here on the file is in place under its bought-file name; a crash now leaves exactly what the next sync
    # adopts by itself (planner rules 2a and 5a; an MP3 would then be judged by its AIFF)
    ex = Executor(paths, state, rep.RunLog(now()), None, lambda path: found, now=now)
    ex.run([Action("adopt_bought", track_id, e["folder"], track_of(track_id, e), (0, 0), src=dest)])
    result = ex.log.results[-1]
    if result.section == "errors":
        raise OpProblem(f"The file is in {dest}, but adding it did not work ({result.note}). The next sync tries "
                        "again.", "failed")
    return result


def _superseded_name(paths: Paths, state: dict, track_id: str, e: dict) -> str:
    stem, ext = split_name(strip_id_suffix(PurePosixPath(e["path"]).name, track_id))
    return NameReserver(paths.root, state).choose(superseded_dir(e["path"]), stem, ext, track_id)


def _move_away(paths: Paths, state: dict, track_id: str, e: dict, today: str, dst: str | None = None) -> str:
    """The current file goes to Superseded/, mirroring its folder (never deleted); its source is never used again for
    this track and the entry becomes "not found". The next file for this track is a different recording under the same name, so
    the entry asks for a rekordbox check (the old cues belong to the wrong song). Returns where the file went."""
    dst = dst or _superseded_name(paths, state, track_id, e)
    wrong = current_key(e)
    rejected = sorted(set(e.get("rejected_sources") or []) | ({wrong} if wrong else set()))
    run_op(paths, state, track_id, [(e["path"], dst)], {
        **e, "path": None, "status": "missing", "source": None, "source_id": None, "source_format": None,
        "cutoff_hz": None, "source_kbps": None, "rejected_sources": rejected, "last_attempt": None, "upgrade": None,
        "rekordbox_check": {"reason": "wrong_song", "since": today}})
    if e.get("upgrade"):  # a parked better version of the wrong song is stale too
        delete_parked(paths, e["upgrade"]["file"])
    return dst


def refusal(paths: Paths, e: dict, cand: Candidate | None, budget, qobuz: bool) -> str | None:
    """Why "Use this" (or a link) can't go ahead, known before any request to Qobuz; None if it can. `cand` None: not
    known yet (a link). `qobuz`: the version comes from Qobuz."""
    if cand is not None and cand.key == current_key(e):
        return CURRENT_VERSION
    if e.get("path") and not (paths.root / e["path"]).is_file():  # moved in Finder: the next sync finds it again
        return NOT_THERE
    if qobuz and budget.stopped:
        return QOBUZ_PAUSED
    if qobuz and budget.exhausted():
        return (f"Not downloaded: {budget.why_exhausted()}. Try again tomorrow, or allow a few extra downloads on the "
                "Qobuz page.")
    return None


def _premium(cand: Candidate, service: str, account, fallback, track: SourceTrack, emit: Emit) -> bool:
    """Before "Use this" downloads through an account: its formats, listed through the login exactly like in a run
    (Acquirer.premium: the same warning signs, and the same "premium_missing" when there's no ~256 kbps stream).
    It's the operation's first logged-in request, so no protection pause comes before it, as in a run."""
    return Acquirer(None, fallback, None, NoPacer(), make_ready, emit=emit,
                    accounts={service: account}).premium(cand, service, track)


def use_candidate(paths: Paths, state: dict, track_id: str, cand: Candidate, *, qobuz, fallback, budget,
                  track: SourceTrack | None = None, emit: Emit = no_emit, token: CancelToken | None = None,
                  process: Callable = make_ready, accounts: dict | None = None,
                  now: Callable[[], datetime] = datetime.now) -> Result:
    """"Use this" (or a pasted link): download exactly this version, check its length, convert, analyse and place it
    through run_op. The previous file goes to Superseded/ and its source is never used again for this track. A Qobuz
    download counts toward today's limit and the failure streak like any other (`budget`); a YouTube Music or SoundCloud
    version goes through its account (`accounts`: service -> Budget) while that has downloads left today and its
    formats show a ~256 kbps stream through the login; otherwise it is the free stream. `track`: the track as last read
    from Spotify (album and cover for the tags), else what state.json knows."""
    e = state["tracks"][track_id]
    problem = refusal(paths, e, cand, budget, cand.source == "qobuz")
    if problem:
        raise OpProblem(problem)
    source = qobuz if cand.source == "qobuz" else fallback
    if source is None:
        raise OpProblem("Qobuz is not set up yet, so this version can't be downloaded.")
    service = ACCOUNT_OF.get(cand.source)
    account = (accounts or {}).get(service)
    if account is not None and account.exhausted():
        account = None  # used up or paused today: the free stream, as before
    # where the current file will go, chosen before the download, so that no name problem costs a Qobuz download
    old_dst = _superseded_name(paths, state, track_id, e) if e.get("path") else None
    track = track or track_of(track_id, e)
    token = token or CancelToken()
    tracker = Tracker(emit, token, track_id)
    workdir = paths.tmp / track_id
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        tracker.emit(SourceChosen(track_id, cand.source, "chosen", cand.title, cand.duration_s))
        if account is not None and not _premium(cand, service, account, fallback, track, emit):
            account = None  # no ~256 kbps stream through the login: the free stream, without using up the account
        tracker.step("download")
        try:
            downloaded = source.download(cand, workdir, **({"account": True} if account else {}),
                                         progress=lambda done, total: tracker.progress(done, total, "bytes"))
        except Protected:
            mark_protected(paths, cand.key)
            raise  # the page says so plainly (problem "protected") and takes the version off the list
        except Exception as err:
            if cand.source == "qobuz" and not getattr(err, "permanent", False):
                budget.failed(f"{e['artist']} - {e['title']}: {err}", getattr(err, "signal", "download_rejected"))
            if account is not None:
                account.failed(f"{e['artist']} - {e['title']}: {short_error(err)}",
                               signal_of(err) or "download_rejected")
            raise OpProblem(f"The download did not work ({err}). Nothing was changed.", "failed") from None
        if cand.source == "qobuz":
            budget.count()
            tracker.emit(AccountUsage("qobuz", budget.used_today(), budget.allowance()))
        elif account is not None:
            account.count()
            tracker.emit(AccountUsage(service, account.used_today(), account.allowance()))
        ready = process(downloaded, track, cand, workdir, tracker)
        if ready is None:  # the length check failed: never offered again for this track
            if cand.source == "qobuz":
                budget.note("duration_mismatch", f"{e['artist']} - {e['title']}: Qobuz file {cand.id} does not "
                                                 "have the track's length")
            rejected = sorted(set(e.get("rejected_sources") or []) | {cand.key})
            state["tracks"][track_id] = {**e, "rejected_sources": rejected}
            library.save_state(paths, state)
            raise OpProblem("This version is more than 3 seconds longer or shorter than the playlist track, so "
                            "Discjockey did not use it.")
        old = None
        today = now().date().isoformat()
        if old_dst:
            # two steps, each crash-safe on its own: after the first, the track is simply "not found" again (with the
            # wrong version rejected), which is what the next sync would also work from
            old = _move_away(paths, state, track_id, e, today, old_dst)
        dst = NameReserver(paths.root, state).choose(replacement_dir(e, ready.status),  # next to the old file
                                                     expected_stem(e["artist"], e["title"]), ".aiff", track_id)
        rejected = set(state["tracks"][track_id].get("rejected_sources") or []) - {cand.key}
        run_op(paths, state, track_id, [(ready.path.relative_to(paths.root).as_posix(), dst)], {
            **e, "path": dst, "status": ready.status, "source": ready.source, "source_id": ready.source_id,
            "source_format": ready.source_format, "cutoff_hz": ready.cutoff_hz, "source_kbps": ready.kbps,
            "rejected_sources": sorted(rejected),
            "last_attempt": today, "last_upgrade_check": today, "upgrade": None,
            "rekordbox_check": state["tracks"][track_id].get("rekordbox_check")})
        if e.get("upgrade"):  # stale now: the track got a new file another way (already gone if moved away above)
            delete_parked(paths, e["upgrade"]["file"])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    note = ready.comment + (f"; the old file is kept as {old}" if old else "")
    return _result("replaced", track_id, e, note, status=ready.status, source=ready.source, cutoff_hz=ready.cutoff_hz,
                   path=dst)


def reject_current(paths: Paths, state: dict, track_id: str, now: Callable[[], datetime] = datetime.now) -> Result:
    """"None of these": the current file moves to Superseded/, its source is never used again, and the track
    becomes "not found" so that the next sync searches again."""
    e = state["tracks"][track_id]
    if e["status"] == "missing" or not e.get("path"):
        raise OpProblem("There is no file for this track yet.")
    if not (paths.root / e["path"]).is_file():
        raise OpProblem(NOT_THERE)
    dst = _move_away(paths, state, track_id, e, now().date().isoformat())
    return _result("rejected", track_id, e, f"moved to {dst}; the next sync searches again", status="missing",
                   path=dst)


def rekordbox_checked(paths: Paths, state: dict, track_id: str) -> Result:
    """The user did what the "Check in rekordbox" reminder asked; the reminder goes away."""
    e = state["tracks"][track_id]
    state["tracks"][track_id] = {**e, "rekordbox_check": None}
    library.save_state(paths, state)
    return _result("rekordbox_checked", track_id, e, "checked in rekordbox")
