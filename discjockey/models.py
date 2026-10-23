"""Plain data records shared by all modules."""
from __future__ import annotations

from dataclasses import dataclass, field

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
