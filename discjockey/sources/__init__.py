"""Playlist sources: one module per service that playlists can be read from (`spotify`, `qobuz`, `soundcloud`,
`youtube_music`), behind one interface, and the functions that read a list of `playlists.txt` lines with the
right source.

A source module has:

    SERVICE: str                                            # a key of models.SERVICE_NAMES
    def recognise(link) -> str | None                       # the playlist id when the link is one of its playlists
    def canonical_link(playlist_id) -> str                  # what playlists.txt and the page store
    def login_state(paths) -> LoginState                    # local check only, never a network call; "not_needed"
                                                            # for a service read without a login
    def open(paths, token) -> Reader                        # logs in; raises SourceError
    def expand(link, paths, token) -> str                   # optional: the link a pasted link of this service stands
                                                            # for, or the link unchanged when it is not this
                                                            # service's (may use the network; raises SourceError)
    def left_out(paths, line, paused) -> bool               # optional: the line is not read this time, before any
                                                            # request, and is no problem (a switched-off choice, a
                                                            # paused account); see `left_out` below

A `Reader` (base.py) is a context manager holding one logged-in session: `fetch(line)` reads a playlist's tracks,
`info(playlist_id)` its name, owner and cover. Playlists and songs are named by tokens (models.token): a bare id for
Spotify, `service:id` for every other service.
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Callable
from types import ModuleType

from ..events import CancelToken, Emit, Message, ReadingPlaylist, no_emit
from ..library import SupportPaths
from ..models import SERVICE_NAMES, FetchedPlaylist, PlaylistLine, split_token
from . import qobuz, soundcloud, spotify, youtube_music
from .base import LineSkipped, LoginState, Reader, SourceError

__all__ = ["SOURCES", "LineSkipped", "LoginState", "Reader", "SourceError", "expand", "left_out", "read",
           "read_infos", "recognise", "service_list"]

SOURCES: dict[str, ModuleType] = {
    "spotify": spotify,
    "qobuz": qobuz,
    "soundcloud": soundcloud,
    "youtube_music": youtube_music,
}


def recognise(link: str) -> tuple[str, str] | None:
    """(service, playlist id) of the first source that recognises the link, or None when none does."""
    for service, source in SOURCES.items():
        playlist_id = source.recognise(link)
        if playlist_id is not None:
            return service, playlist_id
    return None


def service_list() -> str:
    """The playlist services in words, in registry order: "Spotify, Qobuz, SoundCloud or YouTube Music". The one place
    the words that name every service come from, so a new service changes no sentence."""
    names = list(SERVICE_NAMES.values())
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def expand(link: str, paths: SupportPaths, token: CancelToken) -> str:
    """The link a pasted playlist link stands for, when its service can say so: a short link names no playlist
    (`on.soundcloud.com/...`), SoundCloud's own likes link no user until the login is asked. A source module may
    define `expand(link, paths, token)`; it returns the link unchanged when it is not its own, so every such source
    is asked, in registry order, and the first that changes the link wins. May use the network; raises SourceError."""
    for source in SOURCES.values():
        handler = getattr(source, "expand", None)
        if handler is None:
            continue
        expanded = handler(link, paths, token)
        if expanded != link:
            return expanded
    return link


def left_out(paths: SupportPaths, line: PlaylistLine, paused: frozenset[str] = frozenset()) -> bool:
    """Whether the line is not read this time, before any request, and is no problem: the sync treats it like a
    switched-off line (its files stay, nothing is raised). Only Liked music, so far (sources-round D6, D7): while
    Settings' choice is off, or the YouTube account is paused today. `paused`: the account services paused today."""
    check = getattr(SOURCES[line.service], "left_out", None)
    return bool(check is not None and check(paths, line, paused))


def read(paths: SupportPaths, lines: list[PlaylistLine], *, emit: Emit = no_emit,
         token: CancelToken | None = None, want_info: bool = False, paused: frozenset[str] = frozenset(),
         on_signal: Callable[[str, str, str], None] | None = None) -> list[FetchedPlaylist]:
    """Reads every line's playlist with its own service's reader, in `playlists.txt` order.

    Lines that are `left_out` are not read and not in the result (like switched-off lines); a service with none left
    is not opened, so its login is not asked either. Every other service the lines use is checked for a login first (a
    missing one raises SourceError(not_set_up) with that service's words, before any network call); then one reader
    per service is opened for the whole read.
    `want_info`: the readers also fill `FetchedPlaylist.info` where reading the tracks tells it for free.
    `paused`: the account services paused today. `on_signal(account service, kind, message)`: a read made with an
    account's login met one of its warning signs (accounts.SIGNALS); such a line is skipped (LineSkipped), the read
    goes on."""
    token = token or CancelToken()
    lines = [line for line in lines if not left_out(paths, line, paused)]
    services = list(dict.fromkeys(line.service for line in lines))
    for service in services:
        login = SOURCES[service].login_state(paths)
        if not login.connected:
            raise SourceError(login.message, "not_set_up", service)
    with ExitStack() as stack:
        readers = {service: stack.enter_context(SOURCES[service].open(paths, token)) for service in services}
        for reader in readers.values():
            reader.want_info = want_info
            reader.on_signal = on_signal
        fetched = []
        for i, line in enumerate(lines, 1):
            token.check()
            emit(ReadingPlaylist(i, len(lines), line.folder))
            try:
                fetched.append(readers[line.service].fetch(line))
            except LineSkipped as e:
                emit(Message("warning", f"{line.folder}: {e}"))
    return fetched


def read_infos(paths: SupportPaths, refs: list[str], infos: dict, token: CancelToken) -> None:
    """Fills `infos[ref]` (a PlaylistInfo) for each playlist ref, one reader per service. A playlist the service says
    it can't show (kind playlist_unreadable) loses its entry. Any other failure is the service's, not the playlist's
    (a login that fails, the service not answering): the entries already in `infos` stay, and the other services are
    read as usual. Only Stop (events.Cancelled) raises."""
    by_service: dict[str, list[tuple[str, str]]] = {}
    for ref in refs:
        service, playlist_id = split_token(ref)
        by_service.setdefault(service, []).append((ref, playlist_id))
    for service, entries in by_service.items():
        source = SOURCES.get(service)
        if source is None:
            continue
        try:
            with source.open(paths, token) as reader:
                for ref, playlist_id in entries:
                    token.check()
                    try:
                        infos[ref] = reader.info(playlist_id)
                    except SourceError as e:
                        if e.kind == "playlist_unreadable":
                            infos.pop(ref, None)
        except SourceError:
            continue
