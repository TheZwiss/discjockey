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


@dataclass(frozen=True)
class PlaylistLine:
    folder: str
    playlist_id: str
    line_no: int


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    title: str
    artists: tuple[str, ...]
    album: str
    image_url: str | None
    duration_ms: int
    isrc: str | None

    @property
    def first_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/track/{self.id}"


@dataclass
class FetchedPlaylist:
    line: PlaylistLine
    tracks: list[SpotifyTrack]
    skipped: list[str]


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
    track: SpotifyTrack
    order: tuple[int, int]  # (playlists.txt line index, position in playlist)
    src: str | None = None  # root-relative file to move/adopt
    dest_dir: str | None = None  # root-relative target directory for move/adopt
    aliases: tuple[str, ...] = ()
    reason: str = ""  # acquire: new | retry | redownload


@dataclass
class Plan:
    state: dict
    actions: list[Action]
    ambiguous: list[tuple[SpotifyTrack, str, list[str]]]
    dropped: list[str]
    notes: list[str] = field(default_factory=list)
    never: list[Action] = field(default_factory=list)  # downloads left out because the user said "never download"


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


@dataclass(frozen=True)
class BatchRow:
    """A move_batches row with its counts (db.batches)."""
    id: int
    started: str
    finished: str | None  # None: still running, or stopped by a crash
    started_by: str  # "tidy" | "save" | "rename" | "undo"
    about: dict | None  # {"from": old, "to": new} for "rename"
    undoes: int | None  # the batch an undo batch undoes
    moved: int
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
