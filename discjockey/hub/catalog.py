"""The catalogue (issue 39, design §8.1): every `@bridge` method of `HubApi` and the command line word it answers to,
as data. The parser, `help --json`, the agent reference and the tests are generated from it, so a method no entry
names, or an entry no method has, fails a test (T1) instead of drifting.

One `Entry` is one command. A method that serves several commands has several entries (`track never` and
`track download` are `never_download` with `never` fixed to True and False; `upgrade list` is `todo` with `filter`
fixed). `kind` is design §5.2's: R read, RJ read that may use the network or run as a job, J write job, J-control
(stops a job), B brief save (no job, answers at once), W window only, dropped.

Flags are not written here. `effective_params(entry)` makes them from the method's signature (`inspect.signature`):
a parameter without a default is a positional, one with a default is `--its-name` (hyphens for underscores, a
trailing `_id` dropped: `plan_id` is `--plan`), a list parameter is a positional that takes many, and a dict
parameter has no word of its own (its entry says which `resolve` kind builds it). An entry's `params` overrides only
what the design names differently. `fixed` binds arguments a command never takes from the user; `match` names the literal words (a login row's service) that pick
the entry when a command has several (`DISPATCH`).

`planned` is "phase N" while the command is not built: T1 counts it as covered, the parser and `help --json` leave
it out, and the last phase's test fails while any is left. `locks` (design §6.1) names the locks a command takes,
per built entry (a later group fills it with its command; T10, tests/test_cli_locks.py, pins it); `schema` names the shape that
answers the method (`shapes.ANSWERS`, read when the entry is made), None while none is mapped."""
from __future__ import annotations

import inspect
import typing
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from .. import missing as missing_rule
from . import select, shapes

Kind = Literal["R", "RJ", "J", "J-control", "B", "W", "dropped"]

LOCKS = ("library", "support", "rekordbox_w", "rekordbox_r")


@dataclass(frozen=True)
class Arg:
    """One argument of a command. `flag` is None for a positional (`positional=True`) or for an argument the command
    never asks for itself: its value is built from another argument by `resolve` (both False). `resolve` names the
    `HubApi.resolve` kind that turns what the user typed (a path, `last`, `folder:<path>`) into the method's argument;
    the command line never looks anything up itself. A `secret` is refused inside `call --args`."""
    flag: str | None = None
    positional: bool = False
    type: str = "str"
    many: bool = False
    resolve: str | None = None
    secret: bool = False


@dataclass(frozen=True)
class Entry:
    method: str
    command: tuple[str, ...]
    kind: Kind
    locks: frozenset[str] = frozenset()
    needs_yes: bool = False
    dry_run: str | None = None          # the method that answers the command's --dry-run
    partial: frozenset[str] = frozenset()  # per-item states that make a run `partial` (filled by group 1.11)
    params: Mapping[str, Arg] = field(default_factory=dict)  # overrides of the generated flags only
    fixed: Mapping[str, object] = field(default_factory=dict)
    match: Mapping[str, str] = field(default_factory=dict)  # words that pick this entry among a command's (a login row's service); not passed to the method
    cli_first: bool = False             # a method the command line needs and the window does not have yet
    planned: str | None = None
    example: str = ""
    schema: str | None = None           # the shape of the method's answer (hub/shapes), from `_e`


WINDOW_ONLY = {"pick_folder": "native_dialog", "quit": "closes_window"}
WINDOW_ONLY_REASONS = frozenset(("native_dialog", "closes_window"))
DROPPED = frozenset(("media_url", "select", "setup_check_account"))

# Commands that run no engine method of their own: the command line's own words.
# The `job` words read the registry directly (`cli/follow.py`); the window's job methods below have no command of their own.
HOUSEKEEPING = (("help",), ("where",), ("app", "open"), ("call",), ("job", "list"), ("job", "show"), ("job", "follow"),
                ("job", "wait"), ("job", "stop"))

PHASE = "phase 1"

# What the window asks before it does a `needs_yes` command, and says under the question: `<command> -> words`. A
# command line that is run without `--yes` answers `refused`, `needs_yes` with these words as `message`; a command
# without a row says the reason's own words. The group that builds a `needs_yes` command adds its row (phase 6 moves
# the words into the entry's own `confirm`).
CONFIRM: dict[str, str] = {
    "upgrade discard": "Throw away the new versions? Your current files stay. These versions are not offered again.",
    "track undo": "Undo the last step of these tracks? Your old files go back where they were.",
    "batch undo": "Undo every step this batch did? Your old files go back where they were.",
    "folder remove": "Stop watching this folder? Discjockey forgets its files; the files stay where they are.",
    "missing remove": f"Remove these songs from your library? {missing_rule.REMOVE_CONFIRM_BODY}",
    "rekordbox restore": "Put rekordbox's whole library back as this backup holds it? Every change made in rekordbox "
                         "since is dropped. Your library as it is now is saved first.",
}


# The verb's own "all" (design §7.3): what `--all` of a command selects, `<command> -> verb` as `select.VERB_ALL` names it.
# A bulk command without a row has no `--all` (the parser does not offer it). The groups that build the other verbs add
# theirs (`aiff convert --all` is a scope, not a list of songs: it is not here, `ALL_METHOD` has it).
ALL_OF: dict[str, str] = {"upgrade apply": select.UPGRADE_ALL, "check done": select.CHECK_DONE,
                          "aiff rename": select.RENAME_ALL, "missing download": select.DOWNLOAD_AGAIN,
                          "missing remove": select.REMOVE_MISSING}

# The commands for songs whose file is missing (issue 43): their `--all` is the Missing files group's, `all` split by action.
MISSING = ("missing download", "missing remove")


# The method that runs a verb's `--all` when it has one of its own (the window's button: `upgrade_all`), `<command> ->
# method`. Every other verb's `--all` is the songs `ALL_OF` selects, given to the verb's ordinary method.
ALL_METHOD: dict[str, str] = {"upgrade apply": "upgrade_all", "aiff convert": "make_aiff"}

# The AIFF commands (`aiff_plan` is their `--dry-run`), and what their `--all` takes besides: `--in C` (Make all lossless
# files AIFF in that view; Rename all in it), `--todo cdj` (Convert all: the CDJ group). Both are named by the Flags field.
AIFF = ("aiff convert", "aiff rename")
ALL_NARROWS: dict[str, tuple[str, ...]] = {"aiff convert": ("where", "todo"), "aiff rename": ("where",)}

# A command that runs only with a switch of its own while the rest of it is not built (phase 1: `sync run` is the sync's last
# phase alone; phase 4 lands the whole sync and removes this): `<command> -> the flag`. The parser offers the flag, and a line
# without it is a usage error (`parser.PHASE_ONLY_WORDS`).
PHASE_ONLY: dict[str, str] = {"sync run": "--auto-upgrade-only"}

# How a command with several non-read entries picks the one that runs, `<command> -> the rule in words` (every such command
# has a row: tests/test_hub_catalog.py). The first four are in `call`/`parser` today; the rest are built by the groups that
# build those commands, which write the dispatch in `call.choose` and test it. `login ...` entries name their service in
# `Entry.match`.
DISPATCH: dict[str, str] = {
    "aiff convert": "`--all` runs make_aiff (ALL_METHOD), named songs or --rows run convert; --dry-run runs aiff_plan",
    "aiff rename": "rename runs the songs; --dry-run and `--all` run aiff_plan with only=rename",
    "upgrade apply": "`--all` runs upgrade_all (ALL_METHOD), named songs run upgrade with --way",
    "sync run": "`--auto-upgrade-only` runs auto_upgrade_run; the whole sync (start_sync) is phase 4's",
    "batch undo": "the id kind of the first word: `aiff:N` runs batch_undo, `moves:N` runs undo_moves",
    "version use": "`--link URL` runs use_link, else a candidate runs use_candidate",
    "duplicate keep": "a file id as the second word runs supersede_duplicate, `--all` runs keep_duplicates",
    "folder crates show": "several folders run set_crates_shown, one runs set_crate_shown",
    "folder crates hide": "several folders run set_crates_shown, one runs set_crate_shown",
    "folder crates default": "several folders run set_crates_shown, one runs set_crate_shown",
    "login check": "the service word: qobuz runs qobuz_check_login, any other runs setup_account with the saved browser",
    "login sign-in": "the service word: spotify runs setup_spotify_login, any other runs account_sign_in",
    "login sign-out": "the service word: spotify runs spotify_sign_out, any other runs setup_forget_account",
    "login skip": "the service word: qobuz runs setup_skip_qobuz, spotify runs setup_skip_spotify",
}

# The built methods that work without a bound music folder (every other one answers `refused`, `no_library` first): a
# fact `help --json` lists as the `no_library` reason. tests/test_cli_housekeeping.py runs every built read with none
# chosen to pin it (`set_auto_upgrade` is a write: probed by hand, it answers `ok` with none chosen).
NEEDS_NO_LIBRARY = frozenset(("settings_view", "rekordbox_status", "set_auto_upgrade"))  # Settings works before a folder is chosen

# The per-item states of an upgrade that make a finished run `partial` (design §4.3: a skipped or failed song)
UPGRADE_PARTIAL = ("skipped", "failed")
# ... of the Auto-upgrade phase alone: only a track that failed (a track that waits for rekordbox or was refused is not a failure, R24)
AUTO_UPGRADE_PARTIAL = ("failed",)
# ... of an undo: a track whose undo was refused (a file changed since, nothing to undo) or failed
UNDO_PARTIAL = ("refused", "failed")
# ... of Download again / Remove from library: a song that was skipped (its file came back, it gets the other action, ...)
MISSING_PARTIAL = ("skipped",)


def primary(entries: "list[Entry]") -> "Entry":
    """The entry a command runs and the parser takes its words from: the write when there is one (a `J` or `B` entry, the
    first), else a read that runs as a job, else the read (`aiff convert` has the read `aiff_plan` among its entries,
    which the write's `--dry-run` runs)."""
    return next((e for e in entries if e.kind in ("J", "B")), next((e for e in entries if e.kind != "R"), entries[0]))


def entry_of(method: str, command: str) -> "Entry | None":
    """The entry of `method` whose command is `command` (a method that serves several commands has several entries)."""
    return next((e for e in by_method(method) if " ".join(e.command) == command), None)


def confirm_words(entry: "Entry") -> str | None:
    """The window's question for `entry`'s command, or None when no row names it (the reason's own words say it)."""
    return CONFIRM.get(" ".join(entry.command) or entry.method)


def _e(method: str, command: str, kind: Kind, example: str = "", *, params: Mapping[str, Arg] | None = None,
       fixed: Mapping[str, object] | None = None, needs_yes: bool = False, dry_run: str | None = None,
       cli_first: bool = False, built: bool = False, locks: Iterable[str] = (), partial: Iterable[str] = (),
       match: Mapping[str, str] | None = None) -> Entry:
    """`built=True` is a command the command line has now (`planned` None); a group sets it when it lands its command.
    `partial`: the per-item states that end a finished run `partial` (design §4.3, R24)."""
    return Entry(method=method, command=tuple(command.split()), kind=kind, needs_yes=needs_yes, dry_run=dry_run,
                 params=params or {}, fixed=fixed or {}, cli_first=cli_first, locks=frozenset(locks),
                 partial=frozenset(partial), match=match or {},
                 planned=None if built or kind in ("W", "dropped") else PHASE, example=example,
                 schema=shapes.ANSWERS.get(method))


def _positional(resolve: str | None = None, *, many: bool = False, type: str = "str") -> Arg:
    return Arg(positional=True, type=type, many=many, resolve=resolve)


def _derived(resolve: str, type: str = "str") -> Arg:
    """An argument the command never asks for: built by `resolve` from another argument."""
    return Arg(type=type, resolve=resolve)


TRACKS = _positional("track", many=True)
TRACK = _positional("track")
SCOPE = {"scope": _derived("aiff_scope", "dict")}
LINES = {"lines": _derived("playlist_lines", "list")}


def _playlist_edits() -> list[Entry]:
    edits = ("add", "remove", "rename", "move", "enable", "disable", "edit")
    out = []
    for op in edits:
        params = {"lines": _derived(f"playlist_lines:{op}", "list"), "loaded_version": _derived("playlist_version"),
                  "files": _derived(f"playlist_files:{op}", "dict")}
        out.append(_e("save_playlists", f"playlist {op}", "J", params=params, dry_run="preview_playlist_change"))
    return out


def _crate_entries() -> list[Entry]:
    out = []
    for word, shown in (("show", True), ("hide", False), ("default", None)):
        out.append(_e("set_crates_shown", f"folder crates {word}", "B", params={"paths": _positional("folder", many=True)},
                      fixed={"shown": shown}))
        out.append(_e("set_crate_shown", f"folder crates {word}", "B", params={"path": _positional("folder")},
                      fixed={"shown": shown}))
    return out


def _favourite_entries() -> list[Entry]:
    return [_e("set_favourites", f"library favourites {op}", "B", params={"keys": _positional(f"favourites:{op}", many=True)})
            for op in ("add", "remove", "move")]


ENTRIES: tuple[Entry, ...] = (
    # --- reads of the library and the screens
    _e("library", "library list", "R", "library list --in all --search love --quality lossless", params={
        "view": Arg("--in", type="str", resolve="collection"), "key": _derived("collection"),
        "query": Arg("--search"), "filter": Arg("--quality"), "sort": Arg("--sort")}),
    _e("track", "track show", "R", 'track show "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff"', params={"track_id": TRACK}, built=True, locks={"rekordbox_r"}),
    _e("todo", "todo list", "R", "todo list --hidden", params={
        "filter": Arg("--group"), "show_hidden": Arg("--hidden", type="bool")}, built=True, locks={"rekordbox_r"}),
    _e("todo", "upgrade list", "R", "upgrade list", params={"show_hidden": Arg("--hidden", type="bool")},
       fixed={"filter": "upgrade_ready"}, built=True, locks={"rekordbox_r"}),
    _e("todo", "missing list", "R", "missing list", params={"show_hidden": Arg("--hidden", type="bool")},
       fixed={"filter": "missing_file"}, built=True, locks={"rekordbox_r"}),
    _e("todo", "check list", "R", "check list", params={"show_hidden": Arg("--hidden", type="bool")},
       fixed={"filter": "rekordbox_check"}, built=True, locks={"rekordbox_r"}),
    _e("sidebar", "library collections", "R", "library collections"),
    _e("watched_folders", "folder list", "R", "folder list"),
    _e("removal_preview", "", "R", params={"folder_id": _positional("folder", type="int")}, built=True),  # `folder remove --dry-run`
    _e("check_import_folder", "folder check", "R", "folder check /Music/Crate"),
    _e("tidy_preview", "tidy run", "R", "tidy run --dry-run"),
    _e("move_batches", "", "R", built=True),  # the window's own list; `batch list` is `batches`
    _e("undo_preview", "batch undo", "R", "batch undo moves:1 --dry-run",
       params={"batch_id": _positional("moves", type="int")}),
    _e("rekordbox_status", "rekordbox status", "R", "rekordbox status", built=True, locks={"rekordbox_r"}),
    _e("job_status", "", "R", built=True),  # the window's own job; `job list` / `job show` read the registry
    _e("spectrum", "track spectrum", "R", "track spectrum local:1 --which current", params={"track_id": TRACK}),
    _e("media_url", "", "dropped"),
    _e("dashboard", "status", "R", "status"),
    _e("runs", "report list", "R", "report list"),
    _e("run", "report show", "R", "report show last", params={"run_id": _positional("report")}, built=True),
    _e("open_report", "open report", "R", "open report last", params={"run_id": _positional("report")}),
    _e("sync_preview", "sync plan", "R", "sync plan"),
    # --- sync and jobs
    _e("refresh", "sync read", "J"),
    _e("stop_refresh", "", "J-control", built=True),  # `job stop` writes the job's stop file (cli/follow.py)
    _e("start_sync", "sync run", "J", params={"selected": _derived("selection", "list")}, dry_run="sync_preview"),
    _e("stop", "", "J-control", built=True),
    _e("stop_sign_in", "", "J-control", built=True),
    _e("never_download", "track never", "J", params={"track_id": TRACKS}, fixed={"never": True}),
    _e("never_download", "track download", "J", params={"track_id": TRACKS}, fixed={"never": False}),
    _e("hide", "track hide", "J", params={"track_id": TRACKS}, fixed={"hidden": True}),
    _e("hide", "track unhide", "J", params={"track_id": TRACKS}, fixed={"hidden": False}),
    _e("setup_status", "setup status", "R", "setup status"),
    _e("app_update", "app info", "R", "app info"),
    _e("rescan_library", "library scan", "J", "library scan", built=True, locks={"library"}),
    _e("quit", "", "W"),
    _e("open_external", "open url", "R", "open url https://example.com"),
    _e("reveal", "open folder", "R", "open folder all"),
    _e("show_in_finder", "open file", "R", "open file local:1", params={
        "track_id": TRACK, "which": Arg("--upgrade", type="bool", resolve="which")}),
    _e("select", "", "dropped"),
    # --- limits
    _e("limits", "limits show", "R", "limits show qobuz", params={"service": _positional()}),
    _e("limits_what_if", "limits set", "R", "limits set qobuz 40 --dry-run", params={
        "service": _positional(), "limit": _positional(type="int")}),
    _e("save_limits", "limits set", "J", params={"service": _positional(), "limit": _positional(type="int")},
       dry_run="limits_what_if"),
    _e("mark_warnings_seen", "limits seen", "J", params={"service": _positional()}),
    # --- playlists
    _e("playlists", "playlist list", "R", "playlist list"),
    _e("add_playlist", "playlist check", "RJ", params={"url": _positional()}),
    _e("preview_playlist_change", "", "R", params={"lines": _derived("playlist_lines", "list")}),
    *_playlist_edits(),
    _e("set_read_liked_music", "settings set read-liked-music", "J", params={"on": _positional(type="bool")}),
    _e("add_liked_music", "playlist add-liked", "J"),
    _e("tidy_up", "tidy run", "J", params={"moves": _positional("tidy_moves", many=True, type="list")},
       dry_run="tidy_preview"),
    _e("undo_moves", "batch undo", "J", params={"batch_id": _positional("moves", type="int")}, needs_yes=True,
       dry_run="undo_preview"),
    # --- logins and setup
    _e("downloads_view", "login list", "R", "login list"),
    _e("find_logins", "login find", "R", "login find soundcloud", params={"service": _positional()}),
    _e("setup_account", "login use", "J", params={"service": _positional(), "browser": Arg("--browser")}),
    _e("setup_account", "login check", "J", params={"service": _positional(), "browser": _derived("saved_browser")}),
    _e("account_sign_in", "login sign-in", "J", params={"service": _positional(), "browser": Arg("--browser")}),
    _e("open_privacy_settings", "open privacy-settings", "R", "open privacy-settings"),
    _e("setup_check_account", "", "dropped"),
    _e("setup_forget_account", "login sign-out", "J", params={"service": _positional()}, needs_yes=True),
    _e("qobuz_check_login", "login check", "J", match={"service": "qobuz"}),
    _e("setup_qobuz_login", "login qobuz", "J", params={
        "email": Arg("--email"), "password": Arg("--password-stdin", type="bool", resolve="stdin", secret=True)}),
    _e("setup_skip_qobuz", "login skip", "J", match={"service": "qobuz"}),
    _e("setup_save_client_id", "login spotify", "J", params={"client_id": Arg("--client-id")}),
    _e("setup_spotify_login", "login sign-in", "J", match={"service": "spotify"}),
    _e("spotify_sign_out", "login sign-out", "J", needs_yes=True, match={"service": "spotify"}),
    _e("setup_skip_spotify", "login skip", "J", match={"service": "spotify"}),
    _e("set_auto_upgrade", "settings set auto-upgrade", "J", "settings set auto-upgrade off",
       params={"on": _positional(type="bool")}, built=True, locks={"library", "support"}),
    _e("setup_check_tools", "tools status", "R", "tools status"),
    _e("update_tools", "tools update", "J"),
    _e("rollback_tools", "tools rollback", "J", needs_yes=True),
    _e("open_licenses", "open licences", "R", "open licences"),
    *_favourite_entries(),
    *_crate_entries(),
    _e("pick_folder", "", "W"),
    _e("check_music_folder", "setup music", "R", "setup music /Music/Discjockey --dry-run", params={"path": _positional()}),
    _e("set_music_folder", "setup music", "J", params={"path": _positional()}, needs_yes=True,
       dry_run="check_music_folder"),
    _e("retry_music_folder", "setup status", "R", "setup status"),
    _e("setup_skip_import", "setup skip-import", "B"),
    _e("add_watched_folder", "folder add", "J", "folder add /Music/Crate", params={"path": _positional()},
       dry_run="check_import_folder", built=True, locks={"library"}),
    _e("start_import", "import run", "J"),
    _e("remove_watched_folder", "folder remove", "J", "folder remove folder:/Music/Crate --dry-run",
       params={"folder_id": _positional("folder", type="int")}, needs_yes=True, dry_run="removal_preview", built=True,
       locks={"library"}),
    # --- questions, duplicates, AIFF, upgrades, rekordbox check
    _e("answer_same_song", "question answer", "J", params={
        "song_key": _derived("question"), "own_key": _derived("question"), "same": _positional(type="bool")}),
    _e("keep_duplicates", "duplicate keep", "J", params={
        "group_id": _positional("duplicate"), "paths": Arg("--all", type="bool", resolve="duplicate_paths")}),
    _e("supersede_duplicate", "duplicate keep", "J", params={
        "group_id": _positional("duplicate"), "file_id": _positional("file", type="int"),
        "paths": _derived("duplicate_paths", "list")}),
    # `aiff convert` is three entries of one command: `convert` (named or --rows songs), `make_aiff` (--all [--in C | --todo
    # cdj]: `ALL_METHOD` swaps it in) and the read that is its `--dry-run` (`aiff_plan`, which a worker runs: it may read
    # files). `aiff rename` is `rename` and its own `aiff_plan` (`only` rename). `help` shows one row for each command.
    _e("convert", "aiff convert", "J", 'aiff convert "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff" --dry-run',
       params={"track_ids": TRACKS, "origin": _derived("aiff_origin")}, dry_run="aiff_plan", built=True,
       locks={"library", "rekordbox_r", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("rename", "aiff rename", "J", 'aiff rename "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff" --dry-run',
       params={"track_ids": TRACKS}, dry_run="aiff_plan", built=True,
       locks={"library", "rekordbox_r", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("make_aiff", "aiff convert", "J", "aiff convert --all --in folder:Library/Hard_Bounce --dry-run", params=SCOPE,
       dry_run="aiff_plan", built=True, locks={"library", "rekordbox_r", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("aiff_plan", "aiff convert", "RJ", "aiff convert --all --todo cdj --dry-run", params={**SCOPE, "only": _derived("aiff_only")},
       dry_run="aiff_plan", built=True, locks={"rekordbox_r"}),
    _e("aiff_plan", "aiff rename", "RJ", "aiff rename --all --dry-run", params=SCOPE, fixed={"only": "rename"},
       dry_run="aiff_plan", built=True, locks={"rekordbox_r"}),
    _e("batch_resume", "batch resume", "J", "batch resume aiff:1", params={"batch_id": _positional("aiff", type="int")},
       built=True, locks={"library", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("batch_undo", "batch undo", "J", "batch undo aiff:1 --dry-run", params={"batch_id": _positional("aiff", type="int")},
       needs_yes=True, dry_run="batch_undo_preview", built=True, locks={"library", "rekordbox_w"},
       partial=UNDO_PARTIAL),
    _e("undo_upgrade", "track undo", "J", 'track undo "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff" --dry-run', params={"track_ids": TRACKS}, needs_yes=True,
       dry_run="undo_upgrade_preview", built=True, locks={"library", "rekordbox_w"}, partial=UNDO_PARTIAL),
    _e("upgrade", "upgrade apply", "J",
       "upgrade apply \"Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff\" --way same-track --dry-run",
       params={"track_ids": TRACKS, "mode": Arg("--way", resolve="upgrade_way")}, dry_run="upgrade_preview", built=True,
       locks={"library", "rekordbox_r", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("upgrade", "upgrade discard", "J", 'upgrade discard "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff" --dry-run', params={"track_ids": TRACKS},
       fixed={"mode": "discard"}, needs_yes=True, dry_run="upgrade_preview", built=True, locks={"library"},
       partial=UPGRADE_PARTIAL),
    _e("upgrade_all", "upgrade apply", "J", "upgrade apply --all --dry-run", built=True,
       locks={"library", "rekordbox_r", "rekordbox_w"}, partial=UPGRADE_PARTIAL),
    _e("rekordbox_checked", "check done", "J", "check done --batch aiff:1",
       params={"track_ids": TRACKS, "batch_id": Arg("--batch", resolve="aiff")}, built=True, locks={"library"},
       partial=UPGRADE_PARTIAL),
    # issue 43: Download again / Remove from library for songs whose file is missing; `missing_files_preview` is their dry run
    # and has no command of its own
    _e("missing_files_preview", "", "R", built=True),
    _e("missing_files", "missing download", "J", "missing download --all --dry-run", params={"track_ids": TRACKS},
       fixed={"action": "download_again"}, dry_run="missing_files_preview", built=True, locks={"library"},
       partial=MISSING_PARTIAL),
    _e("missing_files", "missing remove", "J", "missing remove --all --yes", params={"track_ids": TRACKS},
       fixed={"action": "remove"}, needs_yes=True, dry_run="missing_files_preview", built=True, locks={"library"},
       partial=MISSING_PARTIAL),
    _e("add_bought_file", "version add-file", "J", params={"track_id": TRACK}),
    _e("search_candidates", "version search", "RJ", params={"track_id": TRACK}),
    _e("preview", "version preview", "RJ", params={"track_id": TRACK, "candidate": _positional("candidate", type="dict")}),
    _e("use_candidate", "version use", "J", params={"track_id": TRACK, "candidate": _positional("candidate", type="dict")}),
    _e("use_link", "version use", "J", params={"track_id": TRACK, "url": Arg("--link")}),
    _e("reject_current", "version reject", "J", params={"track_id": TRACK}, needs_yes=True),
    # --- methods the command line needs and the window has not (their shapes belong to the group that builds them)
    _e("freshness", "", "R", cli_first=True, built=True),
    _e("resolve", "", "R", cli_first=True, built=True),
    _e("find_tracks", "track find", "R", "track find get naughty", params={
        "words": Arg(positional=True, many=True), "path": Arg("--path")}, cli_first=True, built=True),
    _e("rekordbox_preview", "rekordbox preview", "R",
       'rekordbox preview "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff"',
       params={"track_id": _positional("track")}, cli_first=True, built=True, locks={"rekordbox_r"}),
    _e("batches", "batch list", "R", "batch list", cli_first=True, built=True),
    _e("batch_detail", "batch show", "R", "batch show aiff:1", params={"batch": _positional("batch")}, cli_first=True,
       built=True),
    _e("select_listing", "", "R", cli_first=True, built=True, locks={"rekordbox_r"}),
    _e("upgrade_preview", "", "R", cli_first=True, built=True, locks={"rekordbox_r"}),
    _e("undo_upgrade_preview", "", "R", cli_first=True, built=True),
    _e("batch_undo_preview", "", "R", cli_first=True, built=True),
    _e("result_words", "", "R", cli_first=True, built=True),
    _e("fill_facts", "library facts", "J", "library facts --dry-run", cli_first=True, dry_run="facts_preview", built=True,
       locks={"library"}),
    _e("facts_preview", "", "R", cli_first=True, built=True),
    # `sync run` is built for the phase alone now (`--auto-upgrade-only`, the parser's `PHASE_ONLY`); `start_sync` is the
    # whole sync (phase 4) and keeps its row planned
    _e("auto_upgrade_preview", "", "R", cli_first=True, built=True, locks={"rekordbox_r"}),
    _e("auto_upgrade_run", "sync run", "J", "sync run --auto-upgrade-only --dry-run", cli_first=True,
       dry_run="auto_upgrade_preview", built=True, locks={"library", "rekordbox_r", "rekordbox_w"},
       partial=AUTO_UPGRADE_PARTIAL),
    _e("settings_view", "settings show", "R", "settings show", cli_first=True, built=True),
    _e("rekordbox_backups", "rekordbox backups", "R", "rekordbox backups", cli_first=True, built=True),
    _e("rekordbox_restore", "rekordbox restore", "J", "rekordbox restore 20261110T090001Z --dry-run", cli_first=True,
       needs_yes=True, dry_run="rekordbox_restore_preview", built=True, locks={"library", "rekordbox_w"}),
    _e("rekordbox_restore_preview", "", "R", cli_first=True, built=True, locks={"rekordbox_r"}),
)

def by_method(method: str) -> list[Entry]:
    return [e for e in ENTRIES if e.method == method]


def _type_of(annotation: object) -> str:
    """`str`, `int`, `bool`, `list` or `dict` from a parameter's annotation (a string here: `from __future__`)."""
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", str(annotation))
    head = text.replace("typing.", "").split("|")[0].strip()
    for name in ("bool", "int", "list", "dict", "float"):
        if head.startswith(name):
            return name
    return "str"


def generated_arg(name: str, parameter: inspect.Parameter) -> Arg:
    """The word a parameter gets when its entry says nothing (see the module docstring)."""
    type_ = _type_of(parameter.annotation)
    resolve = "track" if name in ("track_id", "track_ids") else None
    if type_ == "dict":
        return Arg(type="dict", resolve=resolve)  # an entry names how a dict is built; None here fails T1
    if type_ == "list":
        return Arg(positional=True, type="list", many=True, resolve=resolve)
    if parameter.default is inspect.Parameter.empty:
        return Arg(positional=True, type=type_, resolve=resolve)
    word = name[:-3] if name.endswith("_id") and len(name) > 3 else name
    return Arg(flag="--" + word.replace("_", "-"), type=type_, resolve=resolve)


def effective_params(entry: Entry, signature: inspect.Signature) -> dict[str, Arg]:
    """Every parameter of the method (`signature` without `self`) except those the entry fixes, with its word: the
    entry's own where it names one, else the generated one."""
    out = {}
    for name, parameter in signature.parameters.items():
        if name == "self" or name in entry.fixed:
            continue
        out[name] = entry.params.get(name) or generated_arg(name, parameter)
    return out


def typed_dict_keys(annotation: object) -> frozenset[str]:
    """The keys of a TypedDict annotation, else empty (no bridge parameter has one today)."""
    if isinstance(annotation, type) and typing.is_typeddict(annotation):
        return frozenset(typing.get_type_hints(annotation))
    return frozenset()
