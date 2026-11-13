"""The read-only plan behind "Make all lossless files AIFF", a selection's Convert and the CDJ group's Convert all
(issue 33 stage D; plan rekordbox stage D §0.1, §0.6-§0.8, §1.3). `plan(paths, state, scope, ...)` says which files
become what, how much room the new files need, what is left as it is, and whether the run needs rekordbox closed. The
panel, the commands' `--dry-run` and the job's start all ask this one function (the job plans again at its start and
records the plan's items as the batch; the panel's numbers are a preview).

It only reads. It works from the snapshot and the file facts stored with each own file (`models.entry_audio`), reads the
tags (`tags`, mutagen and ffprobe, milliseconds) only of the own AIFFs in the library format, whose tags decide
between "new tags" and "clean name only", and never decodes a file: not analysed and timing are found by the run. What
rekordbox holds comes from `entries` (a lookup of the tracks that hold a file, one library read the caller opened) and
`rb` (its state). Nothing on disk or in library.db changes.

Scopes: `{"kind": "tracks", "tracks": [key, ...]}` (what the user picked: files with nothing to do are listed in
`skipped` with their reason), `{"kind": "lossless", "view": "all"|"unlisted"|"playlist"|"folder", "key": ...}` (the
view's own files, as `views.library` lists them without filter or search, whose stored codec is lossless by
`quality.is_lossless_codec`) and `{"kind": "cdj"}` (`cdj.group_members`). The "all" scopes leave out what has nothing to
do; `skipped` is for a `tracks` scope only. What can't run now but may later (`WAITING`: the drive is away, the
file is gone, no name, a library rekordbox can't read, a cloud track, no free name, a parked upgrade) is counted in
`waiting` in every scope, each file once and never as an item, so a panel can say "{n} wait" instead of hiding them;
a `tracks` scope lists them in `skipped` as well, with their own words.

The action of each file is `eligible.aiff_action`; a Convert item's names are those `convert.plan_file_names` gives (one
reserver for the whole plan, so two files wanting one name are told apart), a Rename item's `rename.clean_path`. A
library rekordbox can't read (`unreadable`) refuses every Convert and Rename step, a file rekordbox doesn't hold
included (its tracks can't be known), and stops the batch when rekordbox runs: so each of those files waits
(`rekordbox_unreadable`), none is an item, and `needs_closed` is false.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import audio, batches, cdj, convert, db, library, playlists_file as pf, quality, rbstep, rename
from .hub import views
from .library import NameReserver, Paths
from .models import FileAudio, WatchedFolder, entry_audio
from .names import expected_stem, fold
from .rekordbox import eligible
from .rekordbox.eligible import AIFF_EXTS, Eligible
from .rekordbox.master import Entry, Status
from .rekordbox.offset import EntryTiming, TimelineOffset

SCOPE_KINDS = ("tracks", "lossless", "cdj")
SELECTION_LABEL = "Selection"
CDJ_LABEL = "Won't play well on CDJs"
UNREADABLE = "Discjockey couldn't read this file. Nothing was changed."

# the reasons a file can't run now but may later, in the order `waiting` lists them
WAITING = ("away", "file_missing", "no_name", "rekordbox_unreadable", "cloud", "rename_blocked", "upgrade_waits")
NO_FREE_NAME = "no free file name is left for it"

# the kinds in the order the panel lists them: the lossless formats, then the AIFFs that only need a fix, then the
# lossy ones; a codec not listed (WMA, ...) follows by name
KIND_ORDER = ("flac", "wav", "alac", "aiff_hires", "tags", "name", "wavpack", "ape", "tta", "mp3", "aac", "opus",
              "vorbis")
KIND_LABELS = {"flac": "FLAC → AIFF", "wav": "WAV → AIFF", "alac": "ALAC → AIFF",
               "aiff_hires": "AIFF 24-bit or above 44.1 kHz → 16-bit", "tags": "New tags", "name": "Clean name only"}


@dataclass(frozen=True)
class Item:
    """One file the run would change. `kind`: see KIND_ORDER (a codec's own name for a format with no kind of its
    own); `source` the file's format line ("FLAC · 24-bit · 96 kHz"); `path` the file now, `new_path` where it will be
    when the item is done (a Convert whose AIFF takes its clean name at the end: the old file's own path), both
    relative to the music folder; `superseded` where the old file goes (Convert only); `bytes` the room the render
    needs; `old_bytes` the old file's size (what Superseded/ takes); `lossy` whether the old file is lossy; `label` its
    kind's words ("FLAC → AIFF"; not in `to_dict`, the plan's `kinds` carry it)."""
    track: str
    name: str
    action: str
    kind: str
    source: str
    path: str
    new_path: str
    superseded: str | None
    bytes: int
    old_bytes: int
    lossy: bool
    label: str
    cdj: dict | None

    def to_dict(self) -> dict:
        return {"track": self.track, "name": self.name, "action": self.action, "kind": self.kind, "from": self.source,
                "path": self.path, "new_path": self.new_path, "superseded": self.superseded, "bytes": self.bytes,
                "cdj": self.cdj}


@dataclass(frozen=True)
class Left:
    """A file of a `tracks` scope that is left as it is: `reason` an `eligible.REASONS` key, `message` its words."""
    track: str
    name: str
    reason: str
    message: str

    def to_dict(self) -> dict:
        return {"track": self.track, "name": self.name, "reason": self.reason, "message": self.message}


@dataclass(frozen=True)
class AiffPlan:
    scope: dict
    items: tuple[Item, ...]
    skipped: tuple[Left, ...]
    waiting: tuple[dict, ...]
    kinds: tuple[dict, ...]
    lossy: int
    space: tuple[dict, ...]
    superseded_bytes: int
    rekordbox: dict

    @property
    def total(self) -> int:
        return len(self.items)

    def actions(self) -> list[tuple[str, str]]:
        """The items as `batches.start` takes them: (track, action) pairs, in order."""
        return [(i.track, i.action) for i in self.items]

    def to_dict(self) -> dict:
        """The bridge's and the dry run's one shape (plan §1.3)."""
        return {"scope": self.scope, "items": [i.to_dict() for i in self.items],
                "skipped": [s.to_dict() for s in self.skipped], "waiting": list(self.waiting),
                "kinds": list(self.kinds), "lossy": self.lossy,
                "total": self.total, "space": list(self.space), "superseded_bytes": self.superseded_bytes,
                "rekordbox": self.rekordbox}


# --- the pure core: what the items add up to ---

def _kind_rank(kind: str) -> tuple[int, str]:
    return (KIND_ORDER.index(kind), "") if kind in KIND_ORDER else (len(KIND_ORDER), kind)


def kind_of(action: str, audio_: FileAudio, ext: str) -> str:
    """What a file's item is called: `name` for a Rename; for a Convert the lossless format (`flac`, `wav`, `alac`), an
    AIFF that isn't 16/44.1 (`aiff_hires`) or only has the wrong tags (`tags`), else the codec's own name (`mp3`,
    `aac`, `opus`, `wavpack`, ...)."""
    if action == "rename":
        return "name"
    codec = audio_.codec
    if codec.startswith("pcm_"):
        if ext not in AIFF_EXTS:
            return "wav"
        return "tags" if eligible.is_aiff_16_44(ext, codec, audio_.bits, audio_.rate) else "aiff_hires"
    return codec


def kind_label(kind: str, audio_: FileAudio, ext: str) -> str:
    """The words of a kind (plan §3): the fixed ones, else "{format} → AIFF"."""
    return KIND_LABELS.get(kind) or f"{cdj.format_name(audio_, ext)} → AIFF"


def kinds_of(items: Sequence[Item]) -> tuple[dict, ...]:
    """`[{"kind", "label", "n"}]` in KIND_ORDER, only kinds with files."""
    found: dict[str, dict] = {}
    for item in items:
        found.setdefault(item.kind, {"kind": item.kind, "label": item.label, "n": 0})["n"] += 1
    return tuple(found[k] for k in sorted(found, key=_kind_rank))


def format_line(audio_: FileAudio, ext: str) -> str:
    """What the file is now, for the `from` column: "FLAC · 24-bit · 96 kHz", "MP3 · 320 kbps"."""
    parts = [cdj.format_name(audio_, ext)]
    if audio_.bits:
        parts.append(f"{audio_.bits}-bit")
    if audio_.rate:
        parts.append(f"{audio_.rate / 1000:g} kHz")
    if not quality.is_lossless_codec(audio_.codec) and audio_.kbps:
        parts.append(f"{audio_.kbps} kbps")
    return " · ".join(parts)


def waiting_of(counts: Mapping[str, int]) -> tuple[dict, ...]:
    """`[{"reason", "message", "n"}]` for the files that wait, in `WAITING`'s order, only reasons with files."""
    return tuple({"reason": r, "message": batches.words(r, "convert", NO_FREE_NAME if r == "rename_blocked" else None),
                  "n": counts[r]} for r in WAITING if counts.get(r))


def space_of(paths: Paths, items: Sequence[Item], free: Callable[[Path], int]) -> tuple[dict, ...]:
    """The room the new files need, per drive, as `convert.space_needed` counts where a render goes: the drive of
    .discjockey/.tmp (one render at a time: the biggest, or, when it is the target's drive too, every new file) and the
    new files' drive when another. A Rename needs none. `drive` is a folder on the drive."""
    folder_of: dict[int, Path] = {}
    final: dict[int, int] = {}
    peak: dict[int, int] = {}
    for item in items:
        if not item.bytes:
            continue
        places = convert.space_places(paths, item.new_path)
        for place in places:
            folder_of.setdefault(library.device(place), place)
        target = library.device(places[-1])
        final[target] = final.get(target, 0) + item.bytes
        if len(places) > 1:
            tmp = library.device(places[0])
            peak[tmp] = max(peak.get(tmp, 0), item.bytes)
    need = {device: max(final.get(device, 0), peak.get(device, 0)) for device in {*final, *peak}}
    return tuple({"drive": str(folder_of[d]), "needed": n, "free": (room := free(folder_of[d])), "enough": room >= n}
                 for d, n in need.items())


# --- the scopes ---

def _is_lossless(e: dict) -> bool:
    found = entry_audio(e)
    return found is not None and quality.is_lossless_codec(found.codec)


def _view_inputs(paths: Paths, view: str, lines, records, watched) -> tuple[list[pf.Row], Mapping, Sequence]:
    """The playlists.txt lines, read records and watched folders `views.library_files` needs, from the files unless the
    caller has them already (the hub does)."""
    if lines is None:
        lines = pf.load(paths.playlists_file).rows
    if (records is None and view == "playlist") or (watched is None and view == "folder"):
        if paths.db_file.exists():
            with db.connect(paths.db_file) as conn:
                records = db.playlist_records(conn) if records is None else records
                watched = db.watched_folders(conn) if watched is None else watched
    return lines, records or {}, watched or ()


def _pick(paths: Paths, state: dict, scope: Mapping, lines, records, watched
          ) -> tuple[str, list[str], Mapping[str, cdj.CdjProblem]]:
    """The scope's label, its files' keys in order, and (the `cdj` scope) each one's CDJ problem."""
    kind = scope.get("kind")
    if kind == "tracks":
        return SELECTION_LABEL, list(dict.fromkeys(scope["tracks"])), {}
    if kind == "cdj":
        problems = cdj.group_members(state)
        return CDJ_LABEL, list(problems), problems
    if kind == "lossless":
        view, key = scope.get("view", "all"), scope.get("key")
        if view not in views.LIBRARY_VIEWS:
            raise ValueError(f"view must be one of {', '.join(views.LIBRARY_VIEWS)}")
        if view in ("playlist", "folder") and not key:
            raise ValueError(f"a {view} view needs its key")
        lines, records, watched = _view_inputs(paths, view, lines, records, watched)
        found = views.library_files(state, view, key, lines=lines, records=records, watched=watched)
        return found.title, [k for k in found.keys if _is_lossless(state["tracks"][k])], {}
    raise ValueError(f"scope kind must be one of {', '.join(SCOPE_KINDS)}")


# --- one file ---

@dataclass(frozen=True)
class _Skip:
    reason: str
    message: str


def _timing(rb: Status, found: Sequence[Entry]) -> TimelineOffset | None:
    """What `eligible` asks about rekordbox's tracks of the file (a track in Cloud Library Sync refuses): a timeline with
    nothing measured, just those tracks; None when rekordbox holds none."""
    if not found:
        return None
    return TimelineOffset(None, "measured", rb, [EntryTiming(e, 0, False, False, None, None, None) for e in found])


def _judge(paths: Paths, state: dict, key: str, rb: Status, entries: Callable[[Path], Sequence[Entry]] | None,
           tags: Callable[[Path], audio.FileFacts], names: NameReserver,
           problem: cdj.CdjProblem | None) -> tuple[Item | None, _Skip | None, bool]:
    """One file: its Item (or why it has none) and whether its tracks are in rekordbox's library."""
    e = state["tracks"].get(key)
    if e is None:
        return None, _Skip("file_missing", batches.words("file_missing", "convert")), False
    where = batches.present(paths, e)
    if where != "here":
        reason = "away" if where == "away" else "file_missing"
        return None, _Skip(reason, batches.words(reason, "convert")), False
    file = paths.root / e["path"]
    ext = PurePosixPath(e["path"]).suffix.lower()
    stored = entry_audio(e)
    facts = None
    try:
        # only an own AIFF in the library format has tags that matter; a file with no stored facts (the facts fill
        # hasn't reached it) is read once, so a selection still knows what it is
        if stored is None and e.get("source") == eligible.OWN:
            facts = tags(file)
            stored = FileAudio(facts.codec, facts.sample_rate, facts.bits, None)
        if stored is not None and eligible.is_aiff_16_44(ext, stored.codec, stored.bits, stored.rate):
            facts = facts or tags(file)
        else:
            facts = None
    except (RuntimeError, OSError):
        return None, _Skip("file_missing", UNREADABLE), False
    clean = None
    if facts is not None and eligible.is_clean_aiff(facts, e):
        try:
            clean = rename.clean_path(paths, state, key, e, names)
        except FileExistsError:
            clean = None
    found = list(entries(file)) if entries is not None else []
    action, verdict = eligible.aiff_action(e, facts, rb, _timing(rb, found), where, clean)
    if not isinstance(verdict, Eligible):
        return None, _Skip(verdict.reason, batches.words(verdict.reason, action)), bool(found)
    if stored is None:
        return None, _Skip("file_missing", UNREADABLE), bool(found)
    if action == "rename":
        if clean is None:  # no free name for it
            return None, _Skip("rename_blocked", batches.words("rename_blocked", "rename", NO_FREE_NAME)), bool(found)
        names.taken.add(fold(clean))
        new, superseded, needs = clean, None, 0
    else:
        new, superseded = convert.plan_file_names(paths, state, key, e, names)
        chain = fold(f"{PurePosixPath(new).parent}/{expected_stem(e['artist'], e['title'])}.aiff") == fold(e["path"])
        if chain:  # the AIFF takes the ID name, then gives the file its clean name: it ends where the old one was
            new = e["path"]
        try:
            needs = convert.needed_bytes(_seconds(e, file, facts, tags), 2)
        except (RuntimeError, OSError):
            return None, _Skip("file_missing", UNREADABLE), bool(found)
    try:
        old_bytes = file.stat().st_size
    except OSError:
        old_bytes = 0
    kind = kind_of(action, stored, ext)
    item = Item(key, rbstep.track_name(e, key), action, kind, format_line(stored, ext), e["path"], new, superseded,
                needs, old_bytes if action == "convert" else 0, not quality.is_lossless_codec(stored.codec),
                kind_label(kind, stored, ext), _cdj_dict(problem or cdj.cdj_problem(stored, ext)))
    return item, None, bool(found)


def _seconds(e: dict, file: Path, facts: audio.FileFacts | None, tags: Callable[[Path], audio.FileFacts]) -> float:
    """How long the file plays, for the room its AIFF needs: the record's own length when it has one (an own file's is
    the import's probe), else the file's header (`facts`, or one `tags` read: ffprobe, no decoding). A file whose header
    says none counts 0 (RuntimeError / OSError when it can't be read at all)."""
    if e.get("duration_ms"):
        return e["duration_ms"] / 1000
    return (facts or tags(file)).duration_s or 0.0


def _cdj_dict(problem: cdj.CdjProblem | None) -> dict | None:
    return {"short": problem.short, "words": problem.words} if problem is not None else None


# --- the plan ---

def plan(paths: Paths, state: dict, scope: Mapping, *, rb: Status,
         entries: Callable[[Path], Sequence[Entry]] | None = None,
         tags: Callable[[Path], audio.FileFacts] = audio.file_facts, lines: Sequence[pf.Row] | None = None,
         records: Mapping | None = None, watched: Sequence[WatchedFolder] | None = None) -> AiffPlan:
    """The plan for `scope` (see the module's docstring). `rb`: rekordbox's `master.Status`. `entries`: `path ->` the
    rekordbox tracks that hold that file (`Master.entries_for` on a library opened read-only), None when there is no
    library to read (`rb.state` `none`, or one that can't be read). `tags`: reads one file's `audio.FileFacts`.
    `lines`, `records`, `watched`: what a playlist or folder view needs, read from `paths` when not given. Raises
    ValueError for a scope that isn't one of the three."""
    label, keys, problems = _pick(paths, state, scope, lines, records, watched)
    names = NameReserver(paths.root, state)
    selected = scope["kind"] == "tracks"
    items: list[Item] = []
    left: list[Left] = []
    waits: dict[str, int] = {}
    in_rekordbox = False
    for key in keys:
        item, skip, held = _judge(paths, state, key, rb, entries, tags, names, problems.get(key))
        in_rekordbox = in_rekordbox or (item is not None and held)
        if item is not None:
            items.append(item)
            continue
        if skip.reason in WAITING:
            waits[skip.reason] = waits.get(skip.reason, 0) + 1
        if selected:
            e = state["tracks"].get(key)
            left.append(Left(key, rbstep.track_name(e, key) if e else key, skip.reason, skip.message))
    # a library the caller gave no lookup for may hold any of the files
    unknown = bool(items) and rb.state == "ready" and entries is None
    return AiffPlan(
        scope={**scope, "label": label}, items=tuple(items), skipped=tuple(left), waiting=waiting_of(waits),
        kinds=kinds_of(items),
        lossy=sum(1 for i in items if i.lossy), space=space_of(paths, items, convert.free_space),
        superseded_bytes=sum(i.old_bytes for i in items),
        rekordbox={"state": rb.state, "running": rb.running, "needs_closed": in_rekordbox or unknown})
