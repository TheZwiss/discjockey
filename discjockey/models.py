"""Plain data records shared by all modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SOURCE_NAMES = {
    "qobuz": "Qobuz",
    "youtube_music": "YouTube Music",
    "soundcloud": "SoundCloud",
    "youtube": "YouTube",
    "manual": "bought file",
}


# Playlist services (where a playlist and its tracks are read from); SOURCE_NAMES above names the download sources.
SERVICE_NAMES = {"spotify": "Spotify", "qobuz": "Qobuz"}
# A track's page on its service, derived from its id. SoundCloud's links can't be derived from an id (stage 6).
TRACK_LINKS = {
    "spotify": "https://open.spotify.com/track/{id}",
    "qobuz": "https://open.qobuz.com/track/{id}",
}


def token(service: str, id: str) -> str:
    """The name of a song or playlist across services: a Spotify id stays bare (so nothing stored for Spotify
    changes), every other service's id gets `service:` in front."""
    return id if service == "spotify" else f"{service}:{id}"


def split_token(tok: str) -> tuple[str, str]:
    """(service, id) of a token; a string without `:` is a Spotify id."""
    service, sep, id = tok.partition(":")
    return (service, id) if sep else ("spotify", tok)


OWN_PREFIX = "local:"  # the key of a song of the user's own: a file imported from a watched folder (stage 4)


def is_own(key: str) -> bool:
    """A song of the user's own (`local:<n>`): made by the import from one of their files, in no playlist."""
    return key.startswith(OWN_PREFIX)


def track_of(track_id: str, e: dict) -> SourceTrack:
    """The playlist side of an entry (its song key names the service), as far as the records know it (for actions run
    outside a sync, and the upgrade checks of the user's own songs)."""
    service, bare_id = split_token(track_id)
    return SourceTrack(bare_id, e["title"], (e["artist"],), "", None, e["duration_ms"], e.get("isrc"), service)


def track_link(tok: str) -> str | None:
    """The page of the track a token names, or None when its service has no link derivable from an id."""
    service, id = split_token(tok)
    pattern = TRACK_LINKS.get(service)
    return pattern.format(id=id) if pattern else None


@dataclass(frozen=True)
class PlaylistLine:
    folder: str
    playlist_id: str  # the service's own id
    line_no: int
    service: str = "spotify"

    @property
    def ref(self) -> str:
        return token(self.service, self.playlist_id)


@dataclass(frozen=True)
class SourceTrack:
    id: str  # the service's own id (Spotify base62, Qobuz digits as text)
    title: str
    artists: tuple[str, ...]
    album: str
    image_url: str | None
    duration_ms: int
    isrc: str | None
    service: str = "spotify"  # a key of SERVICE_NAMES
    link: str | None = None  # the track's page; filled from TRACK_LINKS when None
    streamable: bool = True  # False: the service lists it but won't deliver it now (Qobuz preview or region)

    def __post_init__(self):
        if self.link is None:
            pattern = TRACK_LINKS.get(self.service)
            if pattern:
                object.__setattr__(self, "link", pattern.format(id=self.id))

    @property
    def first_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def key(self) -> str:
        return token(self.service, self.id)


@dataclass(frozen=True)
class PlaylistInfo:
    """What the playlist page shows for a pasted link, whichever service it came from."""
    service: str
    id: str
    name: str
    owner_id: str
    owner_name: str
    collaborative: bool
    image_url: str | None
    track_count: int | None
    yours: bool
    readable: bool  # set by the source, by its own rule (Spotify: yours or collaborative)


@dataclass
class FetchedPlaylist:
    line: PlaylistLine
    tracks: list[SourceTrack]
    skipped: list[str]
    # What the page shows for the playlist, when reading its tracks already told the source (Qobuz's first page does):
    # the hub then needs no second login to ask. Not part of what two reads of the same tracks compare by.
    info: PlaylistInfo | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Candidate:
    source: str  # qobuz | youtube_music | soundcloud | youtube
    id: str
    title: str
    artist: str
    duration_s: float | None
    url: str | None = None
    isrc: str | None = None
    album: str | None = None
    label: str | None = None
    image_url: str | None = None
    direct: bool = False  # SoundCloud: download the artist's original file (its download button), not the stream

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"


@dataclass(frozen=True)
class Action:
    kind: str  # move | adopt | adopt_bought | acquire | upgrade
    track_id: str  # state key
    folder: str  # desired folder
    track: SourceTrack
    order: tuple[int, int]  # (playlists.txt line index, position in playlist)
    src: str | None = None  # root-relative file to move/adopt
    dest_dir: str | None = None  # root-relative target directory for move/adopt
    aliases: tuple[str, ...] = ()
    reason: str = ""  # acquire: new | retry | redownload
    qobuz_id: str | None = None  # acquire/upgrade: the Qobuz track to try first (a Qobuz playlist named it)


@dataclass(frozen=True)
class Question:
    """"Is this the same song?" (plan library stage 4, I4): a playlist song that a file of the user's own might be.
    Until the answer the song isn't downloaded (D4)."""
    song_key: str  # the playlist song's key, or its track token while it has none
    track: SourceTrack
    folder: str  # the playlist song's folder
    own_key: str
    file_id: int  # the own song's file
    why: str  # "artist" | "no_artist" | "length" | "no_length" (the same artist and title, a length unknown)
    delta_s: int | None  # own length - track length, whole seconds (signed); None when a length isn't known


@dataclass
class Plan:
    state: dict
    actions: list[Action]
    ambiguous: list[tuple[str, SourceTrack, str, list[str]]]  # (song key, its first fetched track, folder, files)
    dropped: list[str]
    notes: list[str] = field(default_factory=list)
    never: list[Action] = field(default_factory=list)  # downloads left out because the user said "never download"
    questions: list[Question] = field(default_factory=list)  # held songs waiting for "Is this the same song?"
    duplicates: list[DuplicateGroup] = field(default_factory=list)  # same-song groups (same-audio: db.duplicate_groups)
    deferred_checks: int = 0  # first upgrade checks left for later runs by the cap (D9)


@dataclass(frozen=True)
class Placed:
    path: str
    status: str
    source: str
    source_id: str | None
    source_format: str
    cutoff_hz: int | None
    kbps: int | None = None  # lossy downloads: the source's bitrate


@dataclass(frozen=True)
class Outcome:
    kind: str  # placed | parked | missing | checked | queued (an upgrade check) | errored | skipped
    placed: Placed | None = None
    rejected: tuple[str, ...] = ()
    message: str = ""
    upgrade: dict | None = None  # parked: the state entry's `upgrade` record
    free_downloads: tuple[dict, ...] | None = None  # the artists' free downloads found; None: not looked this time
    qobuz_searched: bool = False  # a queued upgrade check: Qobuz was searched without an error and had nothing


class Protected(RuntimeError):
    """The upload is DRM-protected. Discjockey never works around DRM, so this version can't be played or used."""
    permanent = True  # the sync never tries it again for this track


# --- the scanner's records (spec library-and-sources §6) -----------------------------------------------------------

@dataclass(frozen=True)
class WatchedFolder:
    id: int
    path: Path
    kind: str  # library | import


@dataclass(frozen=True)
class KnownFile:
    """A file row of the index, as the scanner sees it."""
    id: int
    folder: int  # watched folder id
    rel: str  # POSIX, NFC, relative to the watched folder
    size: int | None
    mtime_ns: int | None
    content_key: str | None  # None: a migrated file that wasn't on disk
    linked: bool  # linked to a song
    ambiguous: bool  # moved to one of several places; each scan decides again


@dataclass(frozen=True)
class SeenFile:
    """An audio file a scan found on disk."""
    folder: int
    rel: str
    size: int
    mtime_ns: int
    content_key: str


NOT_OPENABLE = "The drive lists this file, but it can't be opened."  # W6's reason for a broken directory entry


@dataclass
class ScanResult:
    """How one scan sorted the files (spec library-and-sources §6.3); db.apply_scan writes it.

    A row whose file is in `retagged`, `replaced` or `moved` is no longer ambiguous. A `moved` target can be a file
    the index already has as an unlinked row (an earlier scan's ambiguous candidate): that row gives way to the moved
    one. `retagged` also carries an ambiguous row whose file is back at its own path.
    """
    offline: list[int] = field(default_factory=list)  # watched folder ids
    unchanged: int = 0
    retagged: list[tuple[int, SeenFile]] = field(default_factory=list)  # file id -> same key, new size/mtime
    replaced: list[tuple[int, SeenFile]] = field(default_factory=list)  # file id -> other key (audio replaced)
    moved: list[tuple[int, SeenFile]] = field(default_factory=list)  # file id -> its one new place
    ambiguous: list[tuple[int, list[str]]] = field(default_factory=list)  # file id -> snapshot paths of candidates
    new: list[SeenFile] = field(default_factory=list)  # unknown keys, incl. every ambiguous candidate
    copies: list[SeenFile] = field(default_factory=list)  # the key of a file that is still there
    gone: list[int] = field(default_factory=list)  # file ids
    held: list[int] = field(default_factory=list)  # file ids that would be gone, left as they are: the file may be
    # in a subfolder that couldn't be listed or be a file that couldn't be read (spec §12); decided on a later scan
    unreadable: list[tuple[int, str, str]] = field(default_factory=list)  # folder id, rel, reason; tried next scan
    unopenable: list[tuple[int, str]] = field(default_factory=list)  # folder id, rel: listed, but its entry can't be
    # looked at (a broken entry on the drive); db.apply_scan lists a new one in an import folder as unreadable


@dataclass(frozen=True)
class ScanSummary:
    """What one scan of the watched folders changed, counted (library.scan_library)."""
    moved: int = 0
    new: int = 0
    gone: int = 0
    replaced: int = 0  # audio replaced outside Discjockey
    copies: int = 0  # new files with the audio of a file that is still there
    offline: int = 0  # watched folders that couldn't be seen


# --- the move log (spec library-and-sources §5.2, §8.4; plan library stage 2, I3) ---

@dataclass(frozen=True)
class PlannedMove:
    """One move tidy.py asks db.start_batch to record. Paths are snapshot paths (`Library/<...>`)."""
    kind: str  # "file" | "folder"
    file_id: int | None  # the file row; None for a folder move
    label: str  # "Artist - Title" of a file, the folder name of a folder move
    src: str
    dst: str
    content_key: str | None  # the file's key when planned (undo needs it unchanged); None for a folder move
    placed_before: str | None  # the file row's placed_by before / after the move (folder moves: None)
    placed_after: str | None
    skip: tuple[str, str | None] | None = None  # (reason, detail): recorded skipped at once (undo's checks)
    files: int | None = None  # a folder move: the files it carried (an undo's plan knows it; a new rename doesn't)


@dataclass(frozen=True)
class MoveRow:
    """A moves row, joined with its file row as it is now."""
    id: int
    batch: int
    seq: int  # order in the batch; an undo goes in reverse
    kind: str
    file_id: int | None  # None: a folder move, or a file row since gone
    label: str
    src: str
    dst: str
    content_key: str | None
    placed_before: str | None
    placed_after: str | None
    state: str  # "planned" | "done" | "skipped"
    reason: str | None  # skip reason code (plan library stage 2, I6)
    detail: str | None  # the failure's words for "failed"
    now_path: str | None  # the file row's snapshot path today (None: no row)
    now_key: str | None  # the file row's content key today
    files: int | None = None  # a folder move: how many files it carried (set when it is done); None otherwise


@dataclass(frozen=True)
class BatchRow:
    """A move_batches row with its counts (db.batches)."""
    id: int
    started: str
    finished: str | None  # None: still running, or stopped by a crash
    started_by: str  # "tidy" | "save" | "rename" | "undo"
    about: dict | None  # {"from": old, "to": new} for "rename"
    undoes: int | None  # the batch an undo batch undoes
    moved: int  # files moved (a folder move counts the files it carried)
    skipped: int
    undoable: int  # done moves whose undo could run today
    undone_by: int | None  # the latest undo batch of this one


@dataclass(frozen=True)
class BatchResult:
    """What every tidy.py entry point returns; views word it."""
    batch_id: int | None  # None: nothing was asked to move
    started_by: str
    moved: int
    skipped: tuple[MoveRow, ...]  # with reason/detail
    stopped: bool


@dataclass(frozen=True)
class SaveChoice:
    """What the Playlists page's save asks for the files it retargets (plan library stage 2, I4)."""
    files: str  # "leave" (they become placed by the user, P1) | "move"
    renames: tuple[tuple[str, str], ...] = ()  # (old folder, new folder) to rename on disk first
    moves: tuple[tuple[int, str], ...] = ()  # (file_id, src as the page showed it)


# --- the import (plan library stage 4, I5, I6) ---

@dataclass(frozen=True)
class ImportRow:
    """A file of an import folder still waiting for one of the import's passes (db.import_waiting: the first,
    db.import_unjudged: the second)."""
    file_id: int
    path: Path  # absolute
    folder: int  # watched folder id
    state: str  # first pass: "new" | "unreadable" (tried again); second: "identified" | "unreadable"


@dataclass(frozen=True)
class ImportCounts:
    """The import's progress in one import folder (db.import_counts); done = files - waiting - identified -
    unreadable."""
    files: int  # every file row of the folder
    waiting: int  # import_state "new": not read yet
    identified: int  # tags read, an own song made; the sound check still to come
    unreadable: int


@dataclass(frozen=True)
class OwnFacts:
    """What the import's first pass read from a file, for its own song (db.add_own_song)."""
    artist: str
    title: str
    album: str | None
    isrc: str | None
    duration_ms: int | None
    codec: str  # the file's source_format
    status: str  # provisional from the codec until the sound check (D1)


@dataclass(frozen=True)
class AddedFolder:
    """A watched folder just added (db.add_watched_folder): its id and the paths of the import folders inside it
    that it took over."""
    id: int
    merged: list[str]


@dataclass(frozen=True)
class RemovalCounts:
    """What removing a watched folder takes away (db.removal_counts): its file rows, and the playlist songs that
    lose their only file there and so download again at the next sync."""
    files: int
    redownload: int


@dataclass(frozen=True)
class DuplicateGroup:
    """Files that are the same audio or the same song (plan library stage 4, I4/I5)."""
    id: str  # "dup:" + "-".join(sorted file ids)
    why: str  # "same_audio" | "same_song"
    file_ids: tuple[int, ...]


def group_id(file_ids) -> str:
    """A duplicate group's id: its file ids, sorted (a new copy makes it another group, so asked again)."""
    return "dup:" + "-".join(str(i) for i in sorted(file_ids))


@dataclass(frozen=True)
class DupFile:
    """One file of a duplicate group, as the Duplicates question shows it (db.group_files)."""
    file_id: int
    song_key: str | None  # None: a file linked to no song
    path: str  # snapshot path
    status: str | None
    cutoff_hz: int | None
    source_format: str | None
    online: bool
    in_playlists: bool
    usable: bool = True  # not held, not ambiguous: a file a move may take (duplicate_groups leaves the others out)
