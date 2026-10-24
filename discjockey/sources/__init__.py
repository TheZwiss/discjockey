"""Playlist sources: one module per service that playlists can be read from (`spotify`; Qobuz joins in group 3),
behind one interface, and the functions that read a list of `playlists.txt` lines with the right source.

A source module has:

    SERVICE: str                                            # a key of models.SERVICE_NAMES
    def recognise(link) -> str | None                       # the playlist id when the link is one of its playlists
    def canonical_link(playlist_id) -> str                  # what playlists.txt and the page store
    def login_state(paths) -> LoginState                    # local check only, never a network call
    def open(paths, token) -> Reader                        # logs in; raises SourceError

A `Reader` (base.py) is a context manager holding one logged-in session: `fetch(line)` reads a playlist's tracks,
`info(playlist_id)` its name, owner and cover. Playlists and songs are named by tokens (models.token): a bare id for
Spotify, `service:id` for every other service.
"""
from __future__ import annotations

from contextlib import ExitStack
from types import ModuleType

from ..events import CancelToken, Emit, ReadingPlaylist, no_emit
from ..library import SupportPaths
from ..models import FetchedPlaylist, PlaylistLine, split_token
from . import spotify
from .base import LoginState, Reader, SourceError

__all__ = ["SOURCES", "LoginState", "Reader", "SourceError", "read", "read_infos", "recognise"]

SOURCES: dict[str, ModuleType] = {
    "spotify": spotify,
}


def recognise(link: str) -> tuple[str, str] | None:
    """(service, playlist id) of the first source that recognises the link, or None when none does."""
    for service, source in SOURCES.items():
        playlist_id = source.recognise(link)
        if playlist_id is not None:
            return service, playlist_id
    return None


def read(paths: SupportPaths, lines: list[PlaylistLine], *, emit: Emit = no_emit,
         token: CancelToken | None = None) -> list[FetchedPlaylist]:
    """Reads every line's playlist with its own service's reader, in `playlists.txt` order.

    Every service the lines use is checked for a login first (a missing one raises SourceError(not_set_up) with that
    service's words, before any network call); then one reader per service is opened for the whole read."""
    token = token or CancelToken()
    services = list(dict.fromkeys(line.service for line in lines))
    for service in services:
        login = SOURCES[service].login_state(paths)
        if login.state != "ok":
            raise SourceError(login.message, "not_set_up", service)
    with ExitStack() as stack:
        readers = {service: stack.enter_context(SOURCES[service].open(paths, token)) for service in services}
        fetched = []
        for i, line in enumerate(lines, 1):
            token.check()
            emit(ReadingPlaylist(i, len(lines), line.folder))
            fetched.append(readers[line.service].fetch(line))
    return fetched


def read_infos(paths: SupportPaths, refs: list[str], infos: dict, token: CancelToken) -> None:
    """Fills `infos[ref]` (a PlaylistInfo) for each playlist ref, one reader per service. A playlist that can't be
    read loses its entry; a service that can't log in leaves the others alone. Only Stop (events.Cancelled) raises."""
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
                    except SourceError:
                        infos.pop(ref, None)
        except SourceError:
            continue
