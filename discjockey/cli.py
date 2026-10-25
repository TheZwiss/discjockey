"""Discjockey command line: the console front end around discjockey.run. Started by `python -m discjockey`
(discjockey/__main__.py), which prepares the tools first."""
from __future__ import annotations

import argparse
import signal
import sys
import time

from . import library, planner, report as rep, run
from .console import ConsolePrinter
from .events import CancelToken
from .library import LockHeld, NoLibrary

CTRL_C_REPEAT_S = 1.0  # uv and caffeinate forward one Ctrl-C a second time; ignore repeats this close together


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discjockey",
        description="Keep your lossless DJ library in sync with your Spotify and Qobuz playlists.",
    )
    p.add_argument("command", nargs="?", choices=["setup", "update", "upgrades", "hub"],
                   help="setup: one-time logins; update: get the newest yt-dlp; "
                        "upgrades: go through the better versions found for your lossy tracks; "
                        "hub: open the Discjockey window")
    p.add_argument("--yes", action="store_true", help="don't ask before starting")
    p.add_argument("--dry-run", action="store_true", help="only show what would happen")
    p.add_argument("--limit", type=_positive_int, metavar="N", help="download at most N tracks this run")
    p.add_argument("--verbose", action="store_true", help="show every search and candidate")
    p.add_argument("--extra", type=_positive_int, metavar="N",
                   help="allow N more Qobuz downloads today (one time)")
    return p.parse_args(argv)


TIDY_WAITING = ("{n} files are not where the playlist order puts them; tidy up in the window.",
                "1 file is not where the playlist order puts it; tidy up in the window.")


def tidy_line(paths: library.Paths) -> str | None:
    """The console's tidy-up line (spec library-and-sources §8.2; the console never moves files): how many files a
    tidy-up would move by default, on the records as the run left them. None at 0, and for records still in
    state.json (a dry run before the migration) or that can't be read."""
    try:
        state = library.load_state(paths)
    except (library.StateError, OSError):
        return None
    if state.get("version") != 2:
        return None
    n = planner.out_of_place(state)
    if n == 0:
        return None
    return TIDY_WAITING[1] if n == 1 else TIDY_WAITING[0].format(n=n)


def _print_tidy_line(paths: library.Paths) -> None:
    if line := tidy_line(paths):
        print(line)


def sync(paths: library.Paths, args: argparse.Namespace) -> int:
    printer = ConsolePrinter(verbose=args.verbose)
    try:
        prep = run.prepare(paths, dry_run=args.dry_run, extra=args.extra, emit=printer)
    except run.SetupProblem as e:
        print(e)
        return 2
    print(rep.render_plan(prep.plan, full=args.dry_run))
    if prep.needs_qobuz:
        print(run.budget_text(prep))
    if args.dry_run:
        print("\nDry run: no music files were changed and no report was written.")
        _print_tidy_line(paths)
        return 0
    if not prep.plan.actions:
        code, path = run.finish_quietly(prep)
        print(f"No downloads needed. Report: {path}")
        if rep.upgrades_waiting(prep.state):
            print(rep.ready_hint(rep.upgrades_waiting(prep.state)))
        _print_tidy_line(paths)
        return code

    if prep.needs_qobuz:
        print("Logging in to Qobuz...")
    try:
        qobuz = run.open_qobuz(prep)
    except run.SetupProblem as e:
        print(e)
        return 2
    if not args.yes and input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
        if qobuz:
            qobuz.close()
        print("Nothing changed.")
        _print_tidy_line(paths)
        return 0

    token = CancelToken()
    first_press: list[float] = []

    def on_ctrl_c(signum, frame):
        now = time.monotonic()
        if not first_press:
            first_press.append(now)
            token.cancel()
            print("\nStopping safely after the current step... (press Ctrl-C again to stop immediately)")
        elif now - first_press[0] >= CTRL_C_REPEAT_S:
            raise KeyboardInterrupt

    previous = signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        code, path = run.execute(prep, qobuz, emit=printer, token=token, limit=args.limit, verbose=args.verbose)
    finally:
        signal.signal(signal.SIGINT, previous)
    if code == 130:
        print("\nStopped. Everything finished so far is saved.")
    print(rep.summary(prep.log, path, rep.upgrades_waiting(prep.state)))
    _print_tidy_line(paths)
    return code


NOT_CHOSEN_TEXT = ("Discjockey doesn't know your music folder yet. Open the Discjockey window and follow Setup, "
                   "or run: discjockey setup")


def missing_text(folder) -> str:
    return (f"Your music folder isn't there: {folder}\nConnect the drive it is on, or choose another folder in the "
            "Discjockey window (Settings, Music folder). Nothing was changed.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    resolved = library.resolve_paths()
    if args.command == "hub":  # opens without a music folder too: Setup (or the missing-folder screen) takes over
        from .hub import app
        return app.main(resolved)  # the hub takes the lock for each change it makes, not for as long as it is open
    if resolved.problem == "missing":
        print(missing_text(resolved.music_folder))
        return 2
    paths = resolved.paths
    try:
        if paths is None:
            if args.command != "setup":
                print(NOT_CHOSEN_TEXT)
                return 2
            from . import setup_cmd
            paths = setup_cmd.ask_music_folder(resolved.support)
        # setup, update and upgrades take the same lock: nothing may change under a running sync
        with library.run_lock(paths.lock):
            if args.command == "setup":
                from . import setup_cmd
                return setup_cmd.run_setup(paths)
            if args.command == "update":
                from . import setup_cmd
                return setup_cmd.run_update(paths.support)
            if args.command == "upgrades":
                from . import upgrades_cmd
                return upgrades_cmd.run_upgrades(paths)
            return sync(paths, args)
    except NoLibrary as e:
        print(e)
        return 2
    except LockHeld:
        print("Another Discjockey run is still going. Wait until it has finished.")
        return 3
    except KeyboardInterrupt:  # Ctrl-C while reading playlists, logging in or at the question
        print("\nStopped.")
        return 130
    except EOFError:  # no keyboard to type into, e.g. started from a prompt that cannot take input
        print("\nDiscjockey needs to ask you something but cannot read your answer here. "
              "Run it in a Terminal window.")
        return 2
