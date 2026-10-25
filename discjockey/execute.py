"""Carries out planned actions. Every file change goes through library.run_op (crash-safe, never overwrites).

Front ends watch through `emit` (events) and stop it through `token` (Cancelled ends the run between steps).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .align import Alignment, compare_files
from .events import (
    ActionFinished, ActionStarted, Cancelled, CancelToken, Emit, PlannedAction, Result, RunStarted, Tracker, error_kind, no_emit,
)
from .library import NameReserver, Paths, delete_parked, run_op, save_state
from .models import Action, Outcome, Placed
from .names import expected_stem, fold, split_name, strip_id_suffix
from .planner import (apply_outcome, folder_dir, replacement_dir, searched_since_check, superseded_dir,
                      upgrades_ready_dir)
from .quality import is_lossless_codec, quality_line, verdict
from .report import RunLog, buy_links

FALLBACK_SOURCES = ("youtube_music", "soundcloud", "youtube")
NEW_SECTION = {"lossless": "new_lossless", "not_lossless": "new_not_lossless", "fake_lossless": "fake"}


@dataclass
class Executor:
    paths: Paths
    state: dict
    log: RunLog
    acquirer: Any
    analyze_file: Callable[[Path], tuple[str, int | None]]
    emit: Emit = no_emit
    token: CancelToken = field(default_factory=CancelToken)
    now: Callable[[], datetime] = datetime.now
    limit: int | None = None
    align_files: Callable[[Path, Path], Alignment] = compare_files  # (current file, new file)
    downloads: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.names = NameReserver(self.paths.root, self.state)

    def run(self, actions: list[Action]) -> None:
        """Raises events.Cancelled when the token is set; everything finished before is saved."""
        self.emit(RunStarted(len(actions), tuple(self._planned(a) for a in actions)))
        for i, a in enumerate(actions, 1):
            try:
                self.token.check()
                self.emit(ActionStarted(i, len(actions), a))
                result = getattr(self, f"_{a.kind}")(a)
            except (Cancelled, KeyboardInterrupt):
                self._mark_stopped(actions[i - 1:])
                raise
            except Exception as e:  # one bad file must not stop this run or every later one
                result = self._result(a, "errors", note=f"{type(e).__name__}: {e}", error_kind="other")
            self.log.add(result)
            self.emit(ActionFinished(a, result))

    # --- helpers ---

    def _mark_stopped(self, rest: list[Action]) -> None:
        """Every planned action gets a Result, also the ones a stop prevented."""
        for a in rest:
            self.log.add(self._result(a, "queued", "stopped before this track was done"))

    def _entry(self, a: Action) -> dict | None:
        return self.state["tracks"].get(a.track_id)

    def _planned(self, a: Action) -> PlannedAction:
        e = self._entry(a)
        artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
        return PlannedAction(a.kind, a.track_id, title, artist, a.track.image_url)

    def _result(self, a: Action, section: str, note: str = "", **fields) -> Result:
        e = self._entry(a)
        artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
        return Result(section, a.folder, artist, title, a.track_id, note, **fields)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.paths.root).as_posix()

    def _choose_for(self, dest_dir: str, name: str, track_id: str) -> str:
        stem, ext = split_name(strip_id_suffix(name, track_id))
        return self.names.choose(dest_dir, stem, ext, track_id)

    def _limit_reached(self) -> bool:
        if self.limit is not None and self.downloads >= self.limit:
            return True
        self.downloads += 1
        return False

    def _set_entry(self, track_id: str, entry: dict | None) -> None:
        if entry is not None:
            self.state["tracks"][track_id] = entry
            save_state(self.paths, self.state)

    def _drop_stale_upgrade(self, before: dict | None) -> None:
        """The entry got a new file (or none) another way, so its parked better version is not needed any more.
        apply_outcome already cleared the record; this deletes the file in Upgrades ready/."""
        if before and before.get("upgrade"):
            delete_parked(self.paths, before["upgrade"]["file"])

    def _placed_result(self, a: Action, section: str, note: str) -> Result:
        e = self._entry(a)
        return self._result(a, section, note, status=e["status"], source=e["source"], cutoff_hz=e["cutoff_hz"],
                            path=e["path"])

    # --- actions (each returns the Result for the report) ---

    def _adopt_bought(self, a: Action) -> Result:
        e = self._entry(a)
        codec, cutoff = self.analyze_file(self.paths.root / a.src)
        status = verdict(is_lossless_codec(codec), cutoff)
        renames = []
        old = e.get("path")
        if old and (self.paths.root / old).exists():
            renames.append((old, self._choose_for(superseded_dir(old), PurePosixPath(old).name, a.track_id)))
        home = replacement_dir(e, status)  # next to the current file (option A), else the placement folder
        dst = a.src
        if fold(str(PurePosixPath(a.src).parent)) != fold(home):
            target = f"{home}/{PurePosixPath(a.src).name}"
            if renames and fold(old) == fold(target):  # the old file leaves this name in the same step: no suffix
                dst = target
            else:
                dst = self._choose_for(home, PurePosixPath(a.src).name, a.track_id)
            renames.append((a.src, dst))
        placed = Placed(dst, status, "manual", None, codec, cutoff)
        entry = apply_outcome(e, a, Outcome("placed", placed), self.now())
        run_op(self.paths, self.state, a.track_id, renames, entry)
        self._drop_stale_upgrade(e)
        return self._placed_result(a, "bought", quality_line("manual", codec, status, cutoff))

    def _acquire(self, a: Action) -> Result:
        if self._limit_reached():
            return self._result(a, "queued", "--limit reached")
        e = self._entry(a)
        artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
        rejected = set(e.get("rejected_sources") or []) if e else set()
        extra: list[str] = []
        if a.reason == "redownload" and e:
            if e.get("path"):  # the old file is gone, so its name may be reused (a scan already dropped it otherwise)
                self.names.release(e["path"])
            if e.get("source") in FALLBACK_SOURCES and e.get("source_id"):
                extra.append(f"{e['source']}:{e['source_id']}")
        workdir = self.paths.tmp / a.track_id
        workdir.mkdir(parents=True, exist_ok=True)
        tracker = Tracker(self.emit, self.token, a.track_id)
        try:
            res = self.acquirer.acquire(a.track, rejected | set(extra), workdir, False, tracker,
                                        exact=a.qobuz_id)
            rejected_now = tuple(extra) + tuple(res.rejected)
            found = None if res.free_downloads is None else tuple(res.free_downloads)
            if res.kind == "queued":
                if e is not None and rejected_now:  # keep what was learned (e.g. a preview) for next time
                    self._set_entry(a.track_id, apply_outcome(e, a, Outcome("errored", rejected=rejected_now),
                                                              self.now()))
                return self._result(a, "queued", res.note)
            if res.kind == "ready":
                r = res.ready
                dst = self.names.choose(folder_dir(a.folder, r.status), expected_stem(artist, title), ".aiff",
                                        a.track_id)
                placed = Placed(dst, r.status, r.source, r.source_id, r.source_format, r.cutoff_hz, r.kbps)
                entry = apply_outcome(e, a, Outcome("placed", placed, rejected_now, free_downloads=found), self.now())
                run_op(self.paths, self.state, a.track_id, [(self._rel(r.path), dst)], entry)
                self._drop_stale_upgrade(e)
                section = "redownloaded" if a.reason == "redownload" else NEW_SECTION[r.status]
                return self._placed_result(a, section, r.comment)
            if res.kind == "missing":
                self._set_entry(a.track_id, apply_outcome(e, a, Outcome("missing", rejected=rejected_now,
                                                                        free_downloads=found), self.now()))
                self._drop_stale_upgrade(e)
                return self._result(a, "missing", f"{buy_links(artist, title)} · a bought copy goes to "
                                                  f"Library/{a.folder}/{expected_stem(artist, title)}.wav",
                                    status="missing", error_kind="not_found")
            message = "; ".join(res.errors)
            self._set_entry(a.track_id, apply_outcome(e, a, Outcome("errored", rejected=rejected_now,
                                                                    message=message), self.now()))
            return self._result(a, "errors", message, error_kind=error_kind(res.errors))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _park(self, a: Action, e: dict, res, tracker: Tracker) -> Result:
        """A lossless version (or a clearly better ~256 kbps stream of a lossy file) was found: measure how it lines up
        with the current file and park it in Upgrades ready/ for the user (discjockey upgrades). Nothing in Library/ or
        Superseded/ changes."""
        r = res.ready
        tracker.step("compare")
        alignment = self.align_files(self.paths.root / e["path"], r.path)
        dst = self.names.choose(upgrades_ready_dir(e["path"]), expected_stem(e["artist"], e["title"]), ".aiff",
                                a.track_id)
        upgrade = {"file": dst, "source": r.source, "source_id": r.source_id, "source_format": r.source_format,
                   "found": self.now().date().isoformat(), "alignment": alignment.to_dict()}
        if r.status != "lossless":  # a better lossy stream from an account (spec §4); lossless parks stay as before
            upgrade.update(status=r.status, kbps=r.kbps, cutoff_hz=r.cutoff_hz)
        found = None if res.free_downloads is None else tuple(res.free_downloads)
        entry = apply_outcome(e, a, Outcome("parked", rejected=tuple(res.rejected), upgrade=upgrade,
                                            free_downloads=found), self.now())
        run_op(self.paths, self.state, a.track_id, [(self._rel(r.path), dst)], entry)
        return self._result(a, "upgrade_ready", f"{alignment.text} · waiting in {dst}", status=e["status"],
                            source=r.source, path=dst, found_status=r.status)

    def _upgrade(self, a: Action) -> Result:
        if self._limit_reached():
            return self._result(a, "queued", "--limit reached")
        e = self._entry(a)
        rejected = set(e.get("rejected_sources") or [])
        if e.get("source") == "qobuz" and e.get("source_id"):
            rejected.add(f"qobuz:{e['source_id']}")
        # a lossy stream download may have a ~256 kbps version through an account (spec §4)
        better = (e.get("source_kbps") if e["status"] == "not_lossless" and e.get("source") in FALLBACK_SOURCES
                  else None)
        # a check that waited for an account already searched the artists' originals and Qobuz: not again before a
        # real check or the weekly wait
        today = self.now().date()
        originals = not searched_since_check(e, "originals_searched", today)
        qobuz = not searched_since_check(e, "qobuz_searched", today)
        workdir = self.paths.tmp / a.track_id
        workdir.mkdir(parents=True, exist_ok=True)
        tracker = Tracker(self.emit, self.token, a.track_id)
        try:
            res = self.acquirer.acquire(a.track, rejected, workdir, True, tracker, better_than=better,
                                        originals=originals, declined=set(e.get("declined_streams") or []),
                                        qobuz=qobuz, exact=a.qobuz_id)
            found = None if res.free_downloads is None else tuple(res.free_downloads)
            if res.kind == "queued":
                if res.rejected or found is not None or res.qobuz_searched:
                    out = Outcome("queued", rejected=tuple(res.rejected), free_downloads=found,
                                  qobuz_searched=res.qobuz_searched)
                    self._set_entry(a.track_id, apply_outcome(e, a, out, self.now()))
                return self._result(a, "queued", res.note)
            if res.kind == "ready":
                return self._park(a, e, res, tracker)
            if res.kind == "missing":
                self._set_entry(a.track_id, apply_outcome(e, a, Outcome("checked", rejected=tuple(res.rejected),
                                                                        free_downloads=found), self.now()))
                return self._result(a, "checked", "no better version found yet", status=e["status"])
            message = "; ".join(res.errors)
            self._set_entry(a.track_id, apply_outcome(e, a, Outcome("errored", rejected=tuple(res.rejected)),
                                                      self.now()))
            return self._result(a, "errors", message, error_kind=error_kind(res.errors))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
