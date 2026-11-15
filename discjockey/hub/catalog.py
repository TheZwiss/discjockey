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
what the design names differently. `fixed` binds arguments a command never takes from the user.

`planned` is "phase N" while the command is not built: T1 counts it as covered, the parser and `help --json` leave
it out, and the last phase's test fails while any is left. `locks` stays empty until group 1.7 fills it for every
built entry; `schema` stays None in phase 1 (phase 2 fills it)."""
from __future__ import annotations

import inspect
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

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
    cli_first: bool = False             # a method the command line needs and the window does not have yet
    planned: str | None = None
    example: str = ""
    schema: str | None = None


WINDOW_ONLY = {"pick_folder": "native_dialog", "quit": "closes_window"}
WINDOW_ONLY_REASONS = frozenset(("native_dialog", "closes_window"))
DROPPED = frozenset(("media_url", "select", "setup_check_account"))

# Commands that run no engine method of their own: the command line's own words.
HOUSEKEEPING = (("help",), ("where",), ("app", "open"), ("call",), ("job", "wait"))

PHASE = "phase 1"


def _e(method: str, command: str, kind: Kind, example: str = "", *, params: Mapping[str, Arg] | None = None,
       fixed: Mapping[str, object] | None = None, needs_yes: bool = False, dry_run: str | None = None,
       cli_first: bool = False, built: bool = False) -> Entry:
    """`built=True` is a command the command line has now (`planned` None); a group sets it when it lands its command."""
    return Entry(method=method, command=tuple(command.split()), kind=kind, needs_yes=needs_yes, dry_run=dry_run,
                 params=params or {}, fixed=fixed or {}, cli_first=cli_first,
                 planned=None if built or kind in ("W", "dropped") else PHASE, example=example)


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
    _e("track", "track show", "R", "track show local:1", params={"track_id": TRACK}),
    _e("todo", "todo list", "R", "todo list --hidden", params={
        "filter": Arg("--group", many=True), "show_hidden": Arg("--hidden", type="bool")}),
    _e("todo", "upgrade list", "R", "upgrade list", params={"show_hidden": Arg("--hidden", type="bool")},
       fixed={"filter": "upgrade_ready"}),
    _e("todo", "check list", "R", "check list", params={"show_hidden": Arg("--hidden", type="bool")},
       fixed={"filter": "rekordbox_check"}),
    _e("sidebar", "library collections", "R", "library collections"),
    _e("watched_folders", "folder list", "R", "folder list"),
    _e("removal_preview", "folder remove", "R", "folder remove folder:/Music/Crate --dry-run",
       params={"folder_id": _positional("folder", type="int")}),
    _e("check_import_folder", "folder check", "R", "folder check /Music/Crate"),
    _e("aiff_plan", "aiff convert", "RJ", params=SCOPE, dry_run="aiff_plan"),
    _e("aiff_plan", "aiff rename", "RJ", params=SCOPE, dry_run="aiff_plan"),
    _e("tidy_preview", "tidy run", "R", "tidy run --dry-run"),
    _e("move_batches", "batch list", "R", "batch list --kind moves"),
    _e("undo_preview", "batch undo", "R", "batch undo moves:1 --dry-run",
       params={"batch_id": _positional("moves", type="int")}),
    _e("rekordbox_status", "rekordbox status", "R", "rekordbox status", built=True),
    _e("job_status", "job list", "R", "job list"),
    _e("job_status", "job show", "R", "job show current"),
    _e("spectrum", "track spectrum", "R", "track spectrum local:1 --which current", params={"track_id": TRACK}),
    _e("media_url", "", "dropped"),
    _e("dashboard", "status", "R", "status"),
    _e("runs", "report list", "R", "report list"),
    _e("run", "report show", "R", "report show last", params={"run_id": _positional("report")}),
    _e("open_report", "open report", "R", "open report last", params={"run_id": _positional("report")}),
    _e("sync_preview", "sync plan", "R", "sync plan"),
    # --- sync and jobs
    _e("refresh", "sync read", "J"),
    _e("stop_refresh", "job stop", "J-control"),
    _e("start_sync", "sync run", "J", params={"selected": _derived("selection", "list")}, dry_run="sync_preview"),
    _e("stop", "job stop", "J-control"),
    _e("stop_sign_in", "job stop", "J-control"),
    _e("never_download", "track never", "J", params={"track_id": TRACKS}, fixed={"never": True}),
    _e("never_download", "track download", "J", params={"track_id": TRACKS}, fixed={"never": False}),
    _e("hide", "track hide", "J", params={"track_id": TRACKS}, fixed={"hidden": True}),
    _e("hide", "track unhide", "J", params={"track_id": TRACKS}, fixed={"hidden": False}),
    _e("setup_status", "setup status", "R", "setup status"),
    _e("app_update", "app info", "R", "app info"),
    _e("rescan_library", "library scan", "J"),
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
    _e("account_sign_in", "login sign-in", "J", params={"service": _positional(), "browser": Arg("--browser")}),
    _e("open_privacy_settings", "open privacy-settings", "R", "open privacy-settings"),
    _e("setup_check_account", "", "dropped"),
    _e("setup_forget_account", "login sign-out", "J", params={"service": _positional()}, needs_yes=True),
    _e("qobuz_check_login", "login check qobuz", "J"),
    _e("setup_qobuz_login", "login qobuz", "J", params={
        "email": Arg("--email"), "password": Arg("--password-stdin", type="bool", resolve="stdin", secret=True)}),
    _e("setup_skip_qobuz", "login skip qobuz", "J"),
    _e("setup_save_client_id", "login spotify", "J", params={"client_id": Arg("--client-id")}),
    _e("setup_spotify_login", "login sign-in spotify", "J"),
    _e("spotify_sign_out", "login sign-out spotify", "J", needs_yes=True),
    _e("setup_skip_spotify", "login skip spotify", "J"),
    _e("set_auto_upgrade", "settings set auto-upgrade", "J", params={"on": _positional(type="bool")}),
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
    _e("add_watched_folder", "folder add", "J", params={"path": _positional()}, dry_run="check_import_folder"),
    _e("start_import", "import run", "J"),
    _e("remove_watched_folder", "folder remove", "J", params={"folder_id": _positional("folder", type="int")},
       needs_yes=True, dry_run="removal_preview"),
    # --- questions, duplicates, AIFF, upgrades, rekordbox check
    _e("answer_same_song", "question answer", "J", params={
        "song_key": _derived("question"), "own_key": _derived("question"), "same": _positional(type="bool")}),
    _e("keep_duplicates", "duplicate keep", "J", params={
        "group_id": _positional("duplicate"), "paths": Arg("--all", type="bool", resolve="duplicate_paths")}),
    _e("supersede_duplicate", "duplicate keep", "J", params={
        "group_id": _positional("duplicate"), "file_id": _positional("file", type="int"),
        "paths": _derived("duplicate_paths", "list")}),
    _e("convert", "aiff convert", "J", params={"track_ids": TRACKS}, dry_run="aiff_plan"),
    _e("rename", "aiff rename", "J", params={"track_ids": TRACKS}, dry_run="aiff_plan"),
    _e("make_aiff", "aiff convert", "J", params=SCOPE, dry_run="aiff_plan"),
    _e("batch_resume", "batch resume", "J", params={"batch_id": _positional("aiff", type="int")}),
    _e("batch_undo", "batch undo", "J", params={"batch_id": _positional("aiff", type="int")}, needs_yes=True),
    _e("undo_upgrade", "track undo", "J", params={"track_ids": TRACKS}, needs_yes=True),
    _e("upgrade", "upgrade apply", "J", params={"track_ids": TRACKS, "mode": Arg("--way", resolve="upgrade_way")}),
    _e("upgrade", "upgrade discard", "J", params={"track_ids": TRACKS}, fixed={"mode": "discard"}, needs_yes=True),
    _e("upgrade_all", "upgrade apply", "J"),
    _e("rekordbox_checked", "check done", "J", params={"track_ids": _positional("track_or_batch", many=True)}),
    _e("add_bought_file", "version add-file", "J", params={"track_id": TRACK}),
    _e("search_candidates", "version search", "RJ", params={"track_id": TRACK}),
    _e("preview", "version preview", "RJ", params={"track_id": TRACK, "candidate": _positional("candidate", type="dict")}),
    _e("use_candidate", "version use", "J", params={"track_id": TRACK, "candidate": _positional("candidate", type="dict")}),
    _e("use_link", "version use", "J", params={"track_id": TRACK, "url": Arg("--link")}),
    _e("reject_current", "version reject", "J", params={"track_id": TRACK}, needs_yes=True),
    # --- methods the command line needs and the window has not (their shapes belong to the group that builds them)
    _e("freshness", "", "R", cli_first=True, built=True),
    _e("resolve", "", "R", cli_first=True, built=True),
    _e("find_tracks", "", "R", cli_first=True),
    _e("rekordbox_preview", "rekordbox preview", "R", cli_first=True),
    _e("batches", "", "R", cli_first=True),
    _e("batch_detail", "batch show", "R", cli_first=True),
    _e("select", "", "R", cli_first=True),
    _e("upgrade_preview", "", "R", cli_first=True),
    _e("fill_facts", "", "J", cli_first=True),
    _e("auto_upgrade_preview", "", "R", cli_first=True),
    _e("auto_upgrade_run", "", "J", cli_first=True),
    _e("settings_view", "settings show", "R", cli_first=True),
    _e("rekordbox_backups", "rekordbox backups", "R", cli_first=True),
    _e("rekordbox_restore", "rekordbox restore", "J", cli_first=True, needs_yes=True),
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
