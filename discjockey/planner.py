"""Pure planning: playlists + state + files on disk + today -> what to do. No I/O, no clock."""
from __future__ import annotations

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath

from .library import op_paths
from .matching import normalize, normalize_artist
from .models import Action, FetchedPlaylist, Outcome, Placed, Plan, SourceTrack
from .names import expected_stem, fold

LOSSY = ("not_lossless", "fake_lossless")
BOUGHT_EXTS = (".aiff", ".aif", ".wav")
WAIT_DAYS = 7
SAME_LENGTH_MS = 3000  # how far apart two lengths may be for one song: an ISRC link and a name link (spec §9.2)
KIND_RANK = {"adopt_bought": 0, "acquire": 1, "upgrade": 2}


def folder_dir(folder: str, status: str) -> str:
    base = f"Library/{folder}"
    return f"{base}/not_lossless" if status in LOSSY else base


# --- placement under option A (spec §7): a file stays where it is; what replaces it lands next to it ---

def _playlist_folder(path: str) -> str | None:
    """`<F>` for a file in a playlist-style folder (`Library/<F>/<name>` or `Library/<F>/not_lossless/<name>`, any
    direct child of `Library/`, in playlists.txt or not), else None."""
    parts = PurePosixPath(path).parts
    if len(parts) == 3 or (len(parts) == 4 and fold(parts[2]) == "not_lossless"):
        return parts[1]
    return None


def mirror_dir(path: str) -> str:
    """The folder a `Library/` file's Superseded/ and Upgrades ready/ copies mirror: `<F>/<subfolders>` for
    `Library/<F>/…/<name>`, without a `not_lossless` directly below `<F>`; "" for a file directly in `Library/`.
    Stage 1 only has `Library/` files; stage 4 adds spec §7's `<watched folder name>/<subfolders>` for import
    folders (it then needs the file's watched folder, which the snapshot will carry)."""
    parts = list(PurePosixPath(path).parent.parts[1:])  # without "Library"
    if len(parts) > 1 and fold(parts[1]) == "not_lossless":
        del parts[1]
    return "/".join(parts)


def superseded_dir(path: str) -> str:
    """Where the file at `path` goes when something replaces it."""
    mirror = mirror_dir(path)
    return f"Superseded/{mirror}" if mirror else "Superseded"


def upgrades_ready_dir(path: str) -> str:
    """Where a better version of the file at `path` waits for the user."""
    mirror = mirror_dir(path)
    return f"Upgrades ready/{mirror}" if mirror else "Upgrades ready"


def replacement_dir(entry: dict, status: str) -> str:
    """Where a file of `status` that replaces the song's current file goes. Without a current file: the placement
    folder (as for a new download). In a playlist-style folder: that folder, so a lossless file leaves its
    `not_lossless/` and a lossy one stays in it. Anywhere else: the current file's folder, unchanged."""
    path = entry.get("path")
    if not path:
        return folder_dir(entry["folder"], status)
    playlist = _playlist_folder(path)
    if playlist is not None:
        return folder_dir(playlist, status)
    return str(PurePosixPath(path).parent)


# --- tidy-up targets (spec §8.1, §8.3): where the playlist order puts a file, under its current name ---

@dataclass(frozen=True)
class TidyRow:
    track_id: str
    file_id: int
    src: str  # snapshot paths; dst = target folder + src's file name
    dst: str
    placed_by: str  # "app" | "user" | "import"
    skip: str | None  # None | "offline" | "not_found" | "name_taken"

    @property
    def ticked(self) -> bool:
        """Ticked by default in the preview: it can move and Discjockey put it where it is."""
        return self.skip is None and self.placed_by == "app"


def tidy_target(entry: dict, folder: str | None = None) -> str | None:
    """Where the entry's file belongs: its placement folder (`folder` overrides the entry's), `not_lossless/` below
    it when lossy, under the file's current name (rekordbox's Relocate finds files by name: a tidy-up never renames).
    None for an entry without a file, one in no playlist, or a file outside `Library/` (stage 2 moves only those)."""
    path = entry.get("path")
    if not path or not entry.get("in_playlists", True):
        return None
    p = PurePosixPath(path)
    if len(p.parts) < 2 or p.parts[0] != "Library":
        return None
    return f"{folder_dir(folder or entry['folder'], entry['status'])}/{p.name}"


def tidy_rows(state: dict, folders: Mapping[str, str] | None = None, *,
              only: Collection[str] | None = None) -> list[TidyRow]:
    """Pure: a row per file whose target folder differs (fold: a case-only difference is no move) from its folder.
    `folders` overrides the entries' folders by key (the save preview's new placement); `only` limits the keys.
    Rows go by source folder, then file name; a target name taken on disk, by another song's row (also a held one) or by another row is `name_taken`, also
    when another row would free it (one more tidy-up moves it, so a batch never depends on its own order). Rows
    ticked by default claim names first, in row order; user/import rows get the names still free."""
    folders = folders or {}
    candidates = []
    for key, e in state["tracks"].items():
        if only is not None and key not in only:
            continue
        dst = tidy_target(e, folders.get(key))
        if dst is None:
            continue
        src = PurePosixPath(e["path"])
        if fold(str(src.parent)) == fold(str(PurePosixPath(dst).parent)):
            continue
        candidates.append(((fold(str(src.parent)), fold(src.name), key), key, e, dst))
    candidates.sort(key=lambda c: c[0])

    on_disk = {fold(f) for f in state.get("files") or []}
    # a row of another song at the target (a held one has no file on disk now) also takes the name: saving two
    # songs on one file is refused
    held_at = {fold(e["path"]) for e in state["tracks"].values() if e.get("path")}
    ambiguous = state.get("ambiguous") or {}
    skips: list[str | None] = []
    for _, key, e, dst in candidates:
        if not e.get("online", True):
            skips.append("offline")
        elif e.get("held") or key in ambiguous or fold(e["path"]) not in on_disk:
            skips.append("not_found")
        else:
            skips.append("name_taken" if fold(dst) in on_disk | held_at else None)
    # Names are claimed in two passes: rows ticked by default first, then user/import rows take what is still free,
    # so a row the user would leave unticked never keeps an app-placed file from moving.
    claimed: set[str] = set()
    for app_pass in (True, False):
        for i, (_, _, e, dst) in enumerate(candidates):
            if skips[i] is not None or (e["placed_by"] == "app") != app_pass:
                continue
            if fold(dst) in claimed:
                skips[i] = "name_taken"
            else:
                claimed.add(fold(dst))
    rows = [TidyRow(key, e["file_id"], e["path"], dst, e["placed_by"], skip)
            for (_, key, e, dst), skip in zip(candidates, skips)]
    return rows


def out_of_place(state: dict) -> int:
    """Files a tidy-up would move by default (the console line and the Playlists page count): user- or
    import-placed files and rows that can't move don't count (plan stage 2, P1)."""
    return sum(1 for r in tidy_rows(state) if r.ticked)


def _due(day: str | None, today: date) -> bool:
    return day is None or (today - date.fromisoformat(day[:10])).days >= WAIT_DAYS


def searched_since_check(entry: dict, key: str, today: date) -> bool:
    """A queued upgrade check's search (`originals_searched`, `qobuz_searched`) still counts: it is later than the
    last real check and the weekly wait hasn't come round since."""
    day = entry.get(key)
    return bool(day) and day > (entry.get("last_upgrade_check") or "") and not _due(day, today)


@dataclass
class _Wanted:
    track: SourceTrack  # the first fetched track (playlist order) that resolved to the song
    folder: str
    order: tuple[int, int]
    aliases: list[str] = field(default_factory=list)
    # the first fetched Qobuz track that resolved to the song and that Qobuz delivers now: the exact id to try first.
    # Only from this read, never from a stored alias: only the read says whether Qobuz delivers it today
    qobuz: SourceTrack | None = None


Lengths = list[tuple[str, int]]  # (song key, its length in ms) of the songs under one ISRC or one name


def _twin(candidates: Lengths, duration_ms: int) -> str | None:
    """The first of `candidates` whose length is within SAME_LENGTH_MS of `duration_ms`."""
    for key, ms in candidates:
        if abs(ms - duration_ms) <= SAME_LENGTH_MS:
            return key
    return None


def _song_name(artist: str, title: str) -> tuple[str, str]:
    """A song's name for a name link: its first artist and its title, normalised as the Qobuz search compares them
    (matching.qobuz_match), so "Artist feat. X" and "Title (Original Mix)" name the same song as the bare ones."""
    return normalize_artist(artist), normalize(title)


def _resolve(fetched: list[FetchedPlaylist], tracks: dict, notes: list[str]) -> dict[str, _Wanted]:
    """Links every fetched track to a song (spec §9.2), in this order: its token is a song's key or alias; else a
    song with the same ISRC and a length within SAME_LENGTH_MS; else, only for a track without an ISRC, a song with
    the same artist, title and length; else it is a new song keyed by its token. A link by ISRC or name adds the
    track's token to the song's aliases (with a note for a stored song). Candidates are the stored songs and the
    songs this read already resolved. Returns the wanted songs by key, in the order they were first met."""
    index: dict[str, str] = {}
    by_isrc: dict[str, Lengths] = {}
    by_name: dict[tuple[str, str], Lengths] = {}
    for key, e in tracks.items():
        index[key] = key
        for alias in e.get("aliases", []):
            index[alias] = key
        if e.get("duration_ms") is None:
            continue
        if e.get("isrc"):
            by_isrc.setdefault(e["isrc"].upper(), []).append((key, e["duration_ms"]))
        if e.get("artist") and e.get("title"):
            by_name.setdefault(_song_name(e["artist"], e["title"]), []).append((key, e["duration_ms"]))

    wanted: dict[str, _Wanted] = {}
    for li, fp in enumerate(fetched):
        for pos, t in enumerate(fp.tracks):
            key = index.get(t.key)
            if key is None:
                name = _song_name(t.first_artist, t.title)
                if t.isrc:
                    key = _twin(by_isrc.get(t.isrc.upper(), []), t.duration_ms)
                    note = (f"{t.first_artist} - {t.title}: same recording as a track you already have "
                            f"(ISRC {t.isrc}), not downloaded again.")
                else:  # a name link only without an ISRC: two different ISRCs are two recordings
                    key = _twin(by_name.get(name, []), t.duration_ms)
                    note = (f"{t.first_artist} - {t.title}: same song as one you already have "
                            f"(same artist, title and length), not downloaded again.")
                if key is None:
                    key = t.key
                    if t.isrc:
                        by_isrc.setdefault(t.isrc.upper(), []).append((key, t.duration_ms))
                    by_name.setdefault(name, []).append((key, t.duration_ms))
                elif key in tracks:
                    tracks[key].setdefault("aliases", []).append(t.key)
                    notes.append(note)
                else:
                    wanted[key].aliases.append(t.key)
                index[t.key] = key
            w = wanted.get(key)
            if w is None:
                w = wanted[key] = _Wanted(t, fp.line.folder, (li, pos))
            if w.qobuz is None and t.service == "qobuz" and t.streamable:
                w.qobuz = t
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
    claimed = {fold(e["path"]) for e in tracks.values() if e.get("path")}
    for op in new_state.get("pending", []):
        claimed.update(fold(p) for p in op_paths(op))
    moved_ambiguous = new_state.get("ambiguous") or {}

    def bought_file(dirs: list[str], e: dict) -> str | None:
        """A bought file under the expected name in one of `dirs` (in that order), not claimed by anything else."""
        stem = expected_stem(e["artist"], e["title"])
        looked: set[str] = set()
        for d in dirs:
            if fold(d) in looked:
                continue
            looked.add(fold(d))
            for ext in BOUGHT_EXTS:
                f = on_disk.get(fold(f"{d}/{stem}{ext}"))
                if f and fold(f) not in claimed:
                    claimed.add(fold(f))
                    return f
        return None

    actions: list[Action] = []
    never: list[Action] = []
    never_ids = new_state.get("never") or {}
    ambiguous: list[tuple[SourceTrack, str, list[str]]] = []
    for key, w in wanted.items():
        def act(kind: str, **kw) -> None:
            skip = kind == "acquire" and key in never_ids  # "never download": nothing is fetched, files stay
            if kind in ("acquire", "upgrade") and w.qobuz:  # a Qobuz playlist named the exact track
                kw["qobuz_id"] = w.qobuz.id
            (never if skip else actions).append(Action(kind, key, w.folder, w.track, w.order, **kw))

        e = tracks.get(key)
        if e is None:  # rule 1
            act("acquire", aliases=tuple(w.aliases), reason="new")
            continue
        if e["status"] == "missing":  # rule 2
            if fold(e["folder"]) != fold(w.folder):
                notes.append(f"{e['artist']} - {e['title']}: now belongs to {w.folder} (still not found).")
            e["folder"] = w.folder
            bought = bought_file([f"Library/{w.folder}"], e)
            if bought:
                act("adopt_bought", src=bought)
            elif e.get("file_gone"):  # a scan found its file gone: downloaded again at once, as before the database
                act("acquire", reason="redownload")
            elif _due(e.get("last_attempt"), today):
                act("acquire", reason="retry")
            continue
        # option A (spec §7): the file stays where it is, whatever folder the song belongs to now; only new downloads
        # follow the placement folder, and the tidy-up (stage 2) is where files move
        e["folder"] = w.folder
        if not e.get("online", True):  # rule 3: on a drive that isn't there; satisfied, nothing to do or check
            continue
        if e.get("held"):  # missing, but the scan couldn't rule out a move (a folder it couldn't read): as offline
            continue
        if key in moved_ambiguous:  # the scan found it in several places (spec §6.3): the user picks one
            ambiguous.append((w.track, w.folder, sorted(moved_ambiguous[key])))
            continue
        if fold(e["path"]) not in on_disk:  # vanished since the scan
            act("acquire", reason="redownload")
            continue
        if e["status"] in LOSSY:  # rule 5
            bought = bought_file([f"Library/{w.folder}", str(PurePosixPath(e["path"]).parent),
                                  replacement_dir(e, "lossless")], e)
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
    if "file_gone" in new:  # dealt with: a new file, or "not found" waiting for its retry like any other
        new["file_gone"] = None
    if outcome.kind == "missing":
        new.update(path=None, status="missing", source=None, source_id=None, source_format=None,
                   cutoff_hz=None, last_attempt=today)
    elif outcome.kind == "placed":
        new.update(_placed_fields(outcome.placed), last_upgrade_check=today)
        if action.kind == "acquire":
            new["last_attempt"] = today
    return new
