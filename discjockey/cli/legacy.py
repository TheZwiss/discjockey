"""The old command line, what is left of it: `setup` and `update`, the two words whose replacements are not built yet.
`parser.route` sends them here. `update` leaves with V4.8b (`tools update`), `setup` and this file with V4.7b (issue 39
phase 4). The sync is `sync run` of the new command line; the bare `discjockey [flags]` sync is gone
(`parser.SYNC_MOVED_WORDS` says so). Started by `python -m discjockey` (discjockey/__main__.py), which prepares the
tools first.

Both words take the library lock, so nothing changes under a running sync. Exit codes: 0 done, 2 setup problem or no
music folder, 3 another run holds the library lock (or a tools job runs, or the support lock stayed held), 130
stopped. The words themselves live in `setup_cmd.py`."""
from __future__ import annotations

import argparse
import sys

from .. import library
from ..library import LockHeld, NoLibrary

LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."
TOOLS_JOB_RUNNING = "Another Discjockey job is already updating the tools. Wait until it has finished."
TOOL_JOBS = ("update_tools", "rollback_tools")  # the support-only jobs of `HubApi._support_job`


def _tools_job_running(support) -> bool:
    """A tools update or rollback of this support folder running in any process (the registry): the terminal's
    `update` gives the refusal `HubApi._support_job` gives, as the library lock alone does not stop it (these jobs hold
    no library lock, only the support lock inside their work)."""
    from ..hub import registry
    return any(state.get("status") in registry.ACTIVE and (state.get("kind") or state.get("method")) in TOOL_JOBS
               for state in registry.Registry(support).list(all=True))


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discjockey",
        description="Keep your lossless DJ library in sync with your Spotify, Qobuz, SoundCloud and YouTube Music "
                    "playlists. The sync is `discjockey sync run`; `discjockey help` lists every command.")
    commands = p.add_subparsers(
        dest="command", metavar="command", title="commands", required=True,
        description="setup: one-time logins; update: get the newest yt-dlp")
    for name, help_text in (("setup", "One-time logins."), ("update", "Get the newest yt-dlp.")):
        commands.add_parser(name, description=help_text)
    return p.parse_args(argv)


NOT_CHOSEN_TEXT = ("Discjockey doesn't know your music folder yet. Open the Discjockey window and follow Setup, "
                   "or run: discjockey setup")


def missing_text(folder) -> str:
    return (f"Your music folder isn't there: {folder}\nConnect the drive it is on, or choose another folder in the "
            "Discjockey window (Settings, Music folder). Nothing was changed.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    resolved = library.resolve_paths()
    if resolved.problem == "missing":
        print(missing_text(resolved.music_folder))
        return 2
    paths = resolved.paths
    try:
        if paths is None:
            if args.command != "setup":
                print(NOT_CHOSEN_TEXT)
                return 2
            from .. import setup_cmd
            paths = setup_cmd.ask_music_folder(resolved.support)
        # setup and update take the same lock: nothing may change under a running sync
        with library.run_lock(paths.lock):
            from .. import setup_cmd
            if args.command == "setup":
                return setup_cmd.run_setup(paths)
            if _tools_job_running(paths.support):
                print(TOOLS_JOB_RUNNING)
                return 3
            return setup_cmd.run_update(paths.support)
    except NoLibrary as e:
        print(e)
        return 2
    except LockHeld:
        print(LOCK_HELD)
        return 3
    except library.SupportBusy as e:  # the support lock stayed held for 2 seconds: say so, no traceback
        print(e)
        return 3
    except KeyboardInterrupt:  # Ctrl-C while logging in or at a question
        print("\nStopped.")
        return 130
    except EOFError:  # no keyboard to type into, e.g. started from a prompt that cannot take input
        print("\nDiscjockey needs to ask you something but cannot read your answer here. "
              "Run it in a Terminal window.")
        return 2
