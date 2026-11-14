"""Discjockey command line: the console front end around discjockey.run. Started by `python -m discjockey`
(discjockey/__main__.py), which prepares the tools first.

The sync (no command) prints its plan, with Auto-upgrade's part (how many upgrades go in at the end, the list in a dry
run), runs, and ends with the report's summary and Auto-upgrade's summary line. With `--json` (needs `--yes` or
`--dry-run`: a command never prompts) stdout holds exactly one object, `{"ok", "exit_code", "dry_run", "report",
"counts", "auto_upgrade"}` or `{"ok": false, "kind", "message"}` for a problem, and every human line goes to stderr
(CONTRIBUTING.md > "Commands for scripts and agents"). Exit codes: 0 done (also when upgrades wait for rekordbox), 1
errors in the run, a crash or `needs_yes`, 2 setup problem or no music folder, 3 another run holds the library lock,
130 stopped. The other commands live in `batch_cmd.py` (`upgrade`, `batch`, `rekordbox checked | backups | restore`),
`convert_cmd.py` (`convert`, `rename`),
`rekordbox_cmd.py` (`rekordbox status | preview`), `settings_cmd.py` (`settings`) and `setup_cmd.py`/`upgrades_cmd.py`."""
from __future__ import annotations

import argparse
import contextlib
import json
import signal
import sys
import time

from . import auto_upgrade, library, planner, report as rep, run
from .console import ConsolePrinter, upgrade_lines, waiting_lines
from .events import CancelToken
from .library import LockHeld, NoLibrary
from .rekordbox import process
from .rekordbox.locate import locate

LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."
CTRL_C_REPEAT_S = 1.0  # uv and caffeinate forward one Ctrl-C a second time; ignore repeats this close together


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def _sync_flags(p: argparse.ArgumentParser, *, repeated: bool = False) -> None:
    """The flags of a sync run. A sub-command repeats them (`discjockey upgrades --yes` keeps working) without
    overwriting what was given before it: `repeated` leaves a flag out of the namespace unless it is typed."""
    extra = {"default": argparse.SUPPRESS} if repeated else {}
    p.add_argument("--yes", action="store_true", help="don't ask before starting", **extra)
    p.add_argument("--dry-run", action="store_true", help="only show what would happen", **extra)
    p.add_argument("--limit", type=_positive_int, metavar="N", help="download at most N tracks this run", **extra)
    p.add_argument("--verbose", action="store_true", help="show every search and candidate", **extra)
    p.add_argument("--extra", type=_positive_int, metavar="N", help="allow N more Qobuz downloads today (one time)",
                   **extra)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discjockey",
        description="Keep your lossless DJ library in sync with your Spotify, Qobuz, SoundCloud and "
                    "YouTube Music playlists. Without a command it runs a sync.",
    )
    _sync_flags(p)
    p.add_argument("--json", action="store_true",
                   help="print one JSON object at the end (the human lines go to stderr); needs --yes or --dry-run")
    commands = p.add_subparsers(
        dest="command", metavar="command", title="commands",
        description="setup: one-time logins; update: get the newest yt-dlp; "
                    "upgrades: go through the better versions found for your lossy tracks; "
                    "upgrade: the same, without prompts (list, apply, discard, undo); "
                    "batch: look at, resume or undo an AIFF batch; "
                    "convert: make files clean AIFFs; rename: give files their clean names; "
                    "settings: change a setting without the window (auto-upgrade); "
                    "hub: open the Discjockey window; rekordbox: rekordbox's library (look at it, check tracks, "
                    "backups)")
    for name, help_text in (("setup", "One-time logins."), ("update", "Get the newest yt-dlp."),
                            ("upgrades", "Go through the better versions found for your lossy tracks."),
                            ("hub", "Open the Discjockey window.")):
        _sync_flags(commands.add_parser(name, description=help_text), repeated=True)
    box = commands.add_parser("rekordbox", description="rekordbox's library: status and preview only read; checked, "
                                                       "backups and restore belong to Same track batches.")
    box_commands = box.add_subparsers(dest="rekordbox_command", metavar="command", required=True)
    status = box_commands.add_parser("status", help="whether Discjockey can read rekordbox's library",
                                     description="Whether rekordbox's library is on this Mac, can be opened, and "
                                                 "whether rekordbox is open. Needs no music folder.")
    preview = box_commands.add_parser(
        "preview", help="what Same track, Convert and Rename would do for one file",
        description="Read only: what each action would do for a song of your library (its key) or for any file "
                    "(--path), and why not when it can't. Decodes the file, which takes a few seconds.")
    preview.add_argument("track", nargs="?", help="the song's key, as the library's JSON prints it")
    preview.add_argument("--path", metavar="FILE", help="a file, instead of a song key")
    for sub in (status, preview):
        sub.add_argument("--json", action="store_true", help="print one JSON object")
    from . import batch_cmd
    batch_parsers = batch_cmd.add_commands(commands, box_commands)
    from . import convert_cmd
    convert_parsers = convert_cmd.add_commands(commands)
    from . import settings_cmd
    settings_cmd.add_commands(commands)
    args = p.parse_args(argv)
    batch_cmd.check_args(args, batch_parsers)
    convert_cmd.check_args(args, convert_parsers)
    if args.json and args.command in ("setup", "update", "upgrades", "hub"):
        p.error(f"--json belongs to the sync, not to `{args.command}`")
    if args.command == "rekordbox" and args.rekordbox_command == "preview" and bool(args.track) == bool(args.path):
        preview.error("give either the song's key or --path FILE")
    return args


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


NEEDS_YES = ("Add --yes to start the sync without a question, or --dry-run to look first. Nothing was changed.")


def _plan_counts(plan) -> dict[str, int]:
    """A dry run's `counts`: the plan's actions by kind (`acquire:new`, `acquire:retry`, `acquire:redownload`,
    `adopt_bought`, `upgrade`), the kinds with none left out."""
    counts: dict[str, int] = {}
    for a in plan.actions:
        key = f"acquire:{a.reason}" if a.kind == "acquire" else a.kind
        counts[key] = counts.get(key, 0) + 1
    return counts


def _run_counts(log: rep.RunLog) -> dict[str, int]:
    """A run's `counts`: the report's sections (`rep.SECTIONS` keys) with at least one result."""
    return {key: len(log.section(key)) for key, _ in rep.SECTIONS if log.section(key)}


def _problem(kind: str, message: str, **extra) -> dict:
    return {"ok": False, "kind": kind, "message": message, **extra}


@contextlib.contextmanager
def _ctrl_c(token: CancelToken):
    """The first Ctrl-C stops the run safely after the current step; a second one, a second later, raises
    KeyboardInterrupt (one press often arrives twice, see CTRL_C_REPEAT_S)."""
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
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def sync(paths: library.Paths, args: argparse.Namespace) -> tuple[int, dict]:
    """A sync run. Returns the exit code and the object `--json` prints for this ending (the human text goes to
    stdout, which `main` points at stderr for `--json`)."""
    printer = ConsolePrinter(verbose=args.verbose)
    try:
        prep = run.prepare(paths, dry_run=args.dry_run, extra=args.extra, emit=printer)
    except run.SetupProblem as e:
        print(e)
        return 2, _problem(e.kind, str(e))
    where = run.folder_names(prep)
    print(rep.render_plan(prep.plan, full=args.dry_run, where=where))
    for line in waiting_lines(prep.import_waiting, len(prep.plan.questions)):
        print(line)
    if prep.needs_qobuz:
        print(run.budget_text(prep))
    # Auto-upgrade's part of the plan: the phase asked in advance what it would do (nothing is written). With the
    # switch off rekordbox isn't looked at at all.
    preview = None
    if prep.settings.auto_upgrade:
        preview = auto_upgrade.run_phase(
            paths, prep.state, {q.song_key for q in prep.plan.questions}, prep.settings, prep.log,
            running=process.running, place=locate(), where=where, dry_run=True)
    name_of = lambda key: _song_name(prep.state, key)  # noqa: E731
    for line in upgrade_lines(preview.to_dict() if preview else None, name_of, full=args.dry_run):
        print(line)
    if args.dry_run:
        print("\nDry run: no music files were changed and no report was written.")
        _print_tidy_line(paths)
        return 0, {"ok": True, "exit_code": 0, "dry_run": True, "report": None, "counts": _plan_counts(prep.plan),
                   "auto_upgrade": preview.to_dict() if preview else None}

    def ended(code: int, path) -> tuple[int, dict]:
        return code, {"ok": True, "exit_code": code, "dry_run": False, "report": str(path),
                      "counts": _run_counts(prep.log), "auto_upgrade": prep.log.auto_upgrade}

    def after(code: int, path) -> None:
        if code == 130:
            print("\nStopped. Everything finished so far is saved.")

    def crashed(e: run.RunCrashed) -> tuple[int, dict]:
        """The sync's `--json` ending for a crash; without `--json` the crash is raised as it always was."""
        if not args.json:
            raise e from e.__cause__
        return 1, _problem("crashed", f"The sync stopped on an unexpected error: {e.error}", report=str(e.report))

    if not prep.plan.actions:
        token = CancelToken()
        try:
            with _ctrl_c(token):
                code, path = run.finish_quietly(prep, emit=printer, token=token, where=where)
        except run.RunCrashed as e:
            return crashed(e)
        after(code, path)
        print(f"No downloads needed. Report: {path}")
        if rep.upgrades_waiting(prep.state):
            print(rep.ready_hint(rep.upgrades_waiting(prep.state)))
        if line := rep.auto_upgrade_line(prep.log.auto_upgrade):
            print(line)
        _print_tidy_line(paths)
        return ended(code, path)

    if prep.needs_qobuz:
        print("Logging in to Qobuz...")
    try:
        qobuz = run.open_qobuz(prep)
    except run.SetupProblem as e:
        print(e)
        return 2, _problem(e.kind, str(e))
    if not args.yes and input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
        if qobuz:
            qobuz.close()
        print("Nothing changed.")
        _print_tidy_line(paths)
        return 0, {"ok": True, "exit_code": 0, "dry_run": False, "report": None, "counts": {}, "auto_upgrade": None}

    token = CancelToken()
    try:
        with _ctrl_c(token):
            code, path = run.execute(prep, qobuz, emit=printer, token=token, limit=args.limit, verbose=args.verbose,
                                     where=where)
    except run.RunCrashed as e:
        return crashed(e)
    after(code, path)
    print(rep.summary(prep.log, path, rep.upgrades_waiting(prep.state)))
    if line := rep.auto_upgrade_line(prep.log.auto_upgrade):
        print(line)
    _print_tidy_line(paths)
    return ended(code, path)


def _song_name(state: dict, key: str) -> str:
    e = state["tracks"].get(key)
    return f"{e['artist']} - {e['title']}" if e else key


NOT_CHOSEN_TEXT = ("Discjockey doesn't know your music folder yet. Open the Discjockey window and follow Setup, "
                   "or run: discjockey setup")


def missing_text(folder) -> str:
    return (f"Your music folder isn't there: {folder}\nConnect the drive it is on, or choose another folder in the "
            "Discjockey window (Settings, Music folder). Nothing was changed.")


def _print_json(data: dict, out) -> None:
    print(json.dumps(data), file=out)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "rekordbox" and args.rekordbox_command in ("status", "preview"):
        from . import rekordbox_cmd  # read only: no lock, and `status` needs no music folder
        return rekordbox_cmd.run(args)
    if args.command in ("upgrade", "batch", "rekordbox"):  # each takes the library lock itself where it writes
        from . import batch_cmd
        return batch_cmd.run(args)
    if args.command in ("convert", "rename"):  # take the lock themselves (a dry run only when facts are missing)
        from . import convert_cmd
        return convert_cmd.run(args)
    if args.command == "settings":  # takes the lock itself where it writes
        from . import settings_cmd
        return settings_cmd.run(args)
    # `--json` is the sync's: one object on stdout at the end, every human line on stderr
    as_json = args.command is None and args.json
    if as_json and not (args.yes or args.dry_run):
        _print_json(_problem("needs_yes", NEEDS_YES), sys.stdout)  # a command never prompts
        return 1
    real_out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr) if as_json else contextlib.nullcontext():
        try:
            code, data = _main(args)
        except Exception as e:  # noqa: BLE001 - `--json` always ends with one object; a bug is a plain failure
            if not as_json:
                raise
            code, data = 1, _problem("failed", f"{type(e).__name__}: {e}")
    if as_json:
        _print_json(data or _problem("failed", "The sync ended without an answer."), real_out)
    return code


def _main(args: argparse.Namespace) -> tuple[int, dict | None]:
    """Everything of `main` that needs a music folder. Returns the exit code and, for the sync, the object `--json`
    prints (None for the other commands, and for endings that print their own text)."""
    resolved = library.resolve_paths()
    if args.command == "hub":  # opens without a music folder too: Setup (or the missing-folder screen) takes over
        from .hub import app
        return app.main(resolved), None  # the hub takes the lock for each change it makes, not for as long as it is open
    if resolved.problem == "missing":
        print(missing_text(resolved.music_folder))
        return 2, _problem("refused", missing_text(resolved.music_folder), reason="no_library")
    paths = resolved.paths
    try:
        if paths is None:
            if args.command != "setup":
                print(NOT_CHOSEN_TEXT)
                return 2, _problem("refused", NOT_CHOSEN_TEXT, reason="no_library")
            from . import setup_cmd
            paths = setup_cmd.ask_music_folder(resolved.support)
        # setup, update and upgrades take the same lock: nothing may change under a running sync
        with library.run_lock(paths.lock):
            if args.command == "setup":
                from . import setup_cmd
                return setup_cmd.run_setup(paths), None
            if args.command == "update":
                from . import setup_cmd
                return setup_cmd.run_update(paths.support), None
            if args.command == "upgrades":
                from . import upgrades_cmd
                return upgrades_cmd.run_upgrades(paths), None
            return sync(paths, args)
    except NoLibrary as e:
        print(e)
        return 2, _problem("refused", str(e), reason="no_library")
    except LockHeld:
        print(LOCK_HELD)
        return 3, _problem("busy", LOCK_HELD)
    except KeyboardInterrupt:  # Ctrl-C while reading playlists, logging in or at the question
        print("\nStopped.")
        return 130, _problem("stopped", "Stopped.")
    except EOFError:  # no keyboard to type into, e.g. started from a prompt that cannot take input
        print("\nDiscjockey needs to ask you something but cannot read your answer here. "
              "Run it in a Terminal window.")
        return 2, None
