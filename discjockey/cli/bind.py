"""The headless `HubApi` (issue 39, design §8.1): the same engine the window uses, bound without a window. Nothing
starts: no console watch, no playlists watch, no drives watch, no media server. No music folder is not an error here:
a method that needs one answers `refused` / `no_library` (`LIBRARY_METHODS`). A write acts on the record as it is now
(`remember=False`): no page showed the person anything to check against."""
from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path

from .. import library
from ..events import CancelToken
from ..hub.api import CliApi
from ..hub.jobs import Job
from ..hub.registry import JobFiles
from ..rekordbox.locate import ENV as REKORDBOX_ENV, SHARE_ENV

SUPPORT_ENV = library.SUPPORT_ENV  # `DISCJOCKEY_SUPPORT`


def headless(resolved: library.Resolved, *, events=None, job: JobFiles | None = None) -> CliApi:
    """`events`: where the engine's events go (a job worker's writer of `events.jsonl`); none for a short command.
    `job`: the job folder of a worker process: its `Jobs` runs inline, as that one job (`Jobs.adopt`), and leaves the
    Mac's staying awake to the worker's `caffeinate`."""
    api = CliApi(resolved.support, events=events, remember=False)
    if job is not None:
        api._jobs.adopt(job)
        api._jobs.keep_awake = lambda reason: nullcontext()
    if resolved.paths is not None:
        api._attach(resolved.paths)
    elif resolved.problem == "missing":
        with api._music_lock:
            api._missing = resolved.music_folder
    return api


def default() -> CliApi:
    """The `HubApi` of the support folder this process works in (`DISCJOCKEY_SUPPORT`, else the real one)."""
    return headless(library.resolve_paths())


def resolved() -> library.Resolved:
    """Where this process finds its folders (`library.resolve_paths`: `DISCJOCKEY_SUPPORT`, else the real support
    folder; `config.json` names the music folder). `where` prints it, so an agent can check it before any write."""
    return library.resolve_paths()


def from_roots(roots: dict) -> library.Resolved:
    """Where a job worker works: the folders its `state.json` names (`roots.music`, `roots.support`), exactly as the
    client saw them when it started the job; the worker's own environment and `config.json` say nothing here. A music
    folder that is not there now (an unplugged drive) is `missing`, none chosen is `not_chosen`."""
    support = Path(roots["support"])
    music = Path(roots["music"]) if roots.get("music") else None
    if music is None:
        return library.Resolved(support, None, "not_chosen", None)
    if not music.is_dir():
        return library.Resolved(support, None, "missing", music)
    return library.Resolved(support, library.Paths(music, support=support), None, music)


def adopt_environment(roots: dict) -> None:
    """Makes the engine code that still reads the environment (rekordbox's lookup, the support folder) see the
    folders of the job's `roots`, not the worker's own environment."""
    os.environ[SUPPORT_ENV] = str(roots["support"])
    os.environ[REKORDBOX_ENV] = str(roots["rekordbox"]) if roots.get("rekordbox") else ""  # empty: no rekordbox library
    os.environ[SHARE_ENV] = str(roots["rekordbox_share"]) if roots.get("rekordbox_share") else ""  # as the client saw it


def job_token(api: CliApi) -> CancelToken:
    """The token of the job a worker's `HubApi` runs (Ctrl-C and the job's `stop` file cancel it)."""
    return api._jobs.inline_token


def last_job(api: CliApi) -> Job | None:
    """The job the worker's `HubApi` ran last (its `finished` and `error` say how it ended)."""
    return api._jobs.current
