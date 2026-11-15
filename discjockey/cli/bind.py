"""The headless `HubApi` (issue 39, design §8.1): the same engine the window uses, bound without a window. Nothing
starts: no console watch, no playlists watch, no drives watch, no media server. No music folder is not an error here:
a method that needs one answers `refused` / `no_library` (`LIBRARY_METHODS`). A write acts on the record as it is now
(`remember=False`): no page showed the person anything to check against."""
from __future__ import annotations

from .. import library
from ..hub.api import CliApi


def headless(resolved: library.Resolved) -> CliApi:
    api = CliApi(resolved.support, events=None, remember=False)
    if resolved.paths is not None:
        api._attach(resolved.paths)
    elif resolved.problem == "missing":
        with api._music_lock:
            api._missing = resolved.music_folder
    return api


def default() -> CliApi:
    """The `HubApi` of the support folder this process works in (`DISCJOCKEY_SUPPORT`, else the real one)."""
    return headless(library.resolve_paths())
