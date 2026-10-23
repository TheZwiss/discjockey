"""Pure planning: playlists + state + files on disk + today -> what to do. No I/O, no clock."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath

from .library import op_paths
from .models import Action, FetchedPlaylist, Outcome, Placed, Plan, SpotifyTrack
from .names import expected_stem, fold

LOSSY = ("not_lossless", "fake_lossless")
BOUGHT_EXTS = (".aiff", ".aif", ".wav")
WAIT_DAYS = 7
ISRC_TOLERANCE_MS = 3000
KIND_RANK = {"move": 0, "adopt": 0, "adopt_bought": 0, "acquire": 1, "upgrade": 2}


def folder_dir(folder: str, status: str) -> str:
    base = f"Library/{folder}"
    return f"{base}/not_lossless" if status in LOSSY else base


def _due(day: str | None, today: date) -> bool:
    return day is None or (today - date.fromisoformat(day[:10])).days >= WAIT_DAYS


def searched_since_check(entry: dict, key: str, today: date) -> bool:
    """A queued upgrade check's search (`originals_searched`, `qobuz_searched`) still counts: it is later than the
    last real check and the weekly wait hasn't come round since."""
    day = entry.get(key)
    return bool(day) and day > (entry.get("last_upgrade_check") or "") and not _due(day, today)


@dataclass
class _Wanted:
    track: SpotifyTrack
    folder: str
    order: tuple[int, int]
    aliases: list[str] = field(default_factory=list)


def _isrc_twin(t: SpotifyTrack, by_isrc: dict[str, list[tuple[str, int]]]) -> str | None:
    if not t.isrc:
        return None
    for key, duration_ms in by_isrc.get(t.isrc.upper(), []):
        if abs(duration_ms - t.duration_ms) <= ISRC_TOLERANCE_MS:
            return key
    return None


def _resolve(fetched: list[FetchedPlaylist], tracks: dict, notes: list[str]) -> dict[str, _Wanted]:
    index: dict[str, str] = {}
    by_isrc: dict[str, list[tuple[str, int]]] = {}
    for key, e in tracks.items():
        index[key] = key
        for alias in e.get("aliases", []):
            index[alias] = key
        if e.get("isrc"):
            by_isrc.setdefault(e["isrc"].upper(), []).append((key, e["duration_ms"]))

    wanted: dict[str, _Wanted] = {}
    for li, fp in enumerate(fetched):
        for pos, t in enumerate(fp.tracks):
            key = index.get(t.id)
            if key is None:
                key = _isrc_twin(t, by_isrc)
                if key is None:
                    key = t.id
                    if t.isrc:
                        by_isrc.setdefault(t.isrc.upper(), []).append((key, t.duration_ms))
                elif key in tracks:
                    tracks[key].setdefault("aliases", []).append(t.id)
                    notes.append(
                        f"{t.first_artist} - {t.title}: same recording as a track you already have "
                        f"(ISRC {t.isrc}), not downloaded again."
                    )
                else:
                    wanted[key].aliases.append(t.id)
                index[t.id] = key
            if key not in wanted:
                wanted[key] = _Wanted(t, fp.line.folder, (li, pos))
    return wanted


def desired_folders(fetched: list[FetchedPlaylist], state: dict) -> dict[str, str]:
    """Pure: the folder every wanted track belongs in (state key -> folder), after identity resolution."""
    return {key: w.folder for key, w in _resolve(fetched, copy.deepcopy(state["tracks"]), []).items()}


def plan(fetched: list[FetchedPlaylist], state: dict, files: list[str], today: date) -> Plan:
    new_state = copy.deepcopy(state)
    tracks: dict = new_state["tracks"]
    notes: list[str] = []
    wanted = _resolve(fetched, tracks, notes)

    dropped: list[str] = []
    for key, e in tracks.items():
        now_in = key in wanted
        if e.get("in_playlists", True) and not now_in:
            dropped.append(key)
        e["in_playlists"] = now_in

    on_disk = {fold(f): f for f in files}
    by_name: dict[str, list[str]] = {}
    for f in files:
        by_name.setdefault(fold(PurePosixPath(f).name), []).append(f)
    claimed = {fold(e["path"]) for e in tracks.values() if e.get("path")}
    for op in new_state.get("pending", []):
        claimed.update(fold(p) for p in op_paths(op))

    def bought_file(folder: str, e: dict) -> str | None:
        stem = expected_stem(e["artist"], e["title"])
        for ext in BOUGHT_EXTS:
            f = on_disk.get(fold(f"Library/{folder}/{stem}{ext}"))
            if f and fold(f) not in claimed:
                claimed.add(fold(f))
                return f
        return None

    actions: list[Action] = []
    never: list[Action] = []
    never_ids = new_state.get("never") or {}
    ambiguous: list[tuple[SpotifyTrack, str, list[str]]] = []
    for key, w in wanted.items():
        def act(kind: str, **kw) -> None:
            skip = kind == "acquire" and key in never_ids  # "never download": nothing is fetched, files stay
            (never if skip else actions).append(Action(kind, key, w.folder, w.track, w.order, **kw))

        e = tracks.get(key)
        if e is None:  # rule 1
            act("acquire", aliases=tuple(w.aliases), reason="new")
            continue
        if e["status"] == "missing":  # rule 2
            if fold(e["folder"]) != fold(w.folder):
                notes.append(f"{e['artist']} - {e['title']}: now belongs to {w.folder} (still not found).")
                e["folder"] = w.folder
            bought = bought_file(w.folder, e)
            if bought:
                act("adopt_bought", src=bought)
            elif _due(e.get("last_attempt"), today):
                act("acquire", reason="retry")
            continue
        if fold(e["path"]) not in on_disk:  # rule 3
            found = [f for f in by_name.get(fold(PurePosixPath(e["path"]).name), []) if fold(f) not in claimed]
            if len(found) == 1:
                claimed.add(fold(found[0]))
                act("adopt", src=found[0], dest_dir=folder_dir(w.folder, e["status"]))
            elif found:
                ambiguous.append((w.track, w.folder, sorted(found)))
            else:
                act("acquire", reason="redownload")
            continue
        if fold(e["folder"]) != fold(w.folder):  # rule 4 (case-only renames are not moves)
            act("move", src=e["path"], dest_dir=folder_dir(w.folder, e["status"]))
        if e["status"] in LOSSY:  # rule 5
            bought = bought_file(w.folder, e)
            if bought:
                act("adopt_bought", src=bought)
            elif not e.get("upgrade") and (_due(e.get("last_upgrade_check"), today)  # none parked yet
                                           or "free_downloads" not in e):  # written before free downloads existed
                act("upgrade")

    actions.sort(key=lambda a: (KIND_RANK[a.kind], a.order))
    return Plan(new_state, actions, ambiguous, dropped, notes, never)


ENTRY_KEYS = (
    "aliases", "isrc", "artist", "title", "duration_ms", "folder", "path", "status", "source",
    "source_id", "source_format", "cutoff_hz", "rejected_sources", "in_playlists", "added",
    "last_attempt", "last_upgrade_check", "upgrade", "source_kbps", "free_downloads", "originals_searched",
    "qobuz_searched",
)


def _placed_fields(p: Placed) -> dict:
    return {"path": p.path, "status": p.status, "source": p.source, "source_id": p.source_id,
            "source_format": p.source_format, "cutoff_hz": p.cutoff_hz, "source_kbps": p.kbps}


def own_key(entry: dict) -> str | None:
    """`<source>:<id>` of the current file (None for a bought file or no file)."""
    if entry.get("path") and entry.get("source") and entry.get("source_id"):
        return f"{entry['source']}:{entry['source_id']}"
    return None


def declined(entry: dict, keys: set[str]) -> dict:
    """The entry with `keys` added to `declined_streams` (unchanged without keys)."""
    if not keys:
        return entry
    return {**entry, "declined_streams": sorted(set(entry.get("declined_streams") or []) | keys)}


def apply_outcome(entry: dict | None, action: Action, outcome: Outcome, now: datetime) -> dict | None:
    """New state entry after an acquisition, upgrade check or bought-file adopt. Entries written before the
    `upgrade` field existed simply lack it (read with .get)."""
    if outcome.kind == "skipped":
        return entry
    today = now.date().isoformat()
    learned = set(outcome.rejected)
    if action.kind == "upgrade" and entry is not None:
        # the current upload's account stream that came out no better isn't the wrong song (rejected_sources, shown
        # in "Wrong song?"): it is the version the user keeps, so it is only declined for later upgrade checks
        own = own_key(entry)
        entry = declined(entry, learned & {own})
        learned.discard(own)
    rejected = sorted(set((entry or {}).get("rejected_sources") or []) | learned)
    if outcome.kind == "errored":
        return None if entry is None else {**entry, "rejected_sources": rejected}
    found = {} if outcome.free_downloads is None else {"free_downloads": list(outcome.free_downloads)}
    if action.kind == "upgrade" and outcome.kind == "queued":
        # waits for an account (spec §4): not stamped as checked, but a working search of the artists' originals
        # or of Qobuz isn't repeated before the next real check or the weekly wait (searched_since_check)
        new = {**entry, "rejected_sources": rejected, **found}
        if outcome.free_downloads is not None:
            new["originals_searched"] = today
        if outcome.qobuz_searched:
            new["qobuz_searched"] = today
        return new
    if action.kind == "upgrade":  # a better version found is only parked; the file stays as it is
        new = {**entry, "rejected_sources": rejected, "last_upgrade_check": today, **found}
        if outcome.kind == "parked":
            new["upgrade"] = outcome.upgrade
        return new

    t = action.track
    if entry is None:
        new = dict.fromkeys(ENTRY_KEYS)
        new.update(aliases=list(action.aliases), isrc=t.isrc, artist=t.first_artist, title=t.title,
                   duration_ms=t.duration_ms, added=now.isoformat(timespec="seconds"))
    else:
        new = dict.fromkeys(ENTRY_KEYS) | entry
    # a new file (or none) another way makes a parked upgrade stale; the executor deletes its file
    new.update(folder=action.folder, in_playlists=True, rejected_sources=rejected, upgrade=None, **found)
    if outcome.kind == "missing":
        new.update(path=None, status="missing", source=None, source_id=None, source_format=None,
                   cutoff_hz=None, last_attempt=today)
    elif outcome.kind == "placed":
        new.update(_placed_fields(outcome.placed), last_upgrade_check=today)
        if action.kind == "acquire":
            new["last_attempt"] = today
    return new
