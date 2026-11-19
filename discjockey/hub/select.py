"""Which songs a listing selects (issue 39, design §7.3): the one answer behind `--rows` and `--all` of the command line
and, from phase 6, the window's select-all. `HubApi.select_listing(listing)` fetches the view the listing names (the
Library's or To-do's, with the filter and the search of the listing) and this module reads the song keys off it, so a
selection is always exactly the rows the screen of that listing shows, never a second rule.

A listing is a mapping:

| key | means |
|---|---|
| `source` | `library` or `todo`; left out it is `todo` when `group` is there, else `library` |
| `in` | a collection: `all` (the default), `unlisted`, `playlist:<folder>`, `folder:<path>` (library only) |
| `search`, `quality` | the Library's search words and quality filter (library only) |
| `group` | a To-do group's key, or `all` (to-do only) |
| `hidden` | whether To-do's hidden songs are listed too (to-do only) |
| `verb_all` | the verb's own "all" button (`VERB_ALL`): the songs that button acts on, with nothing else in the listing (`rename_all` takes an `in` too, the collection whose files it looks at, and a `plan`, the dry run whose songs it runs as well) |

A key its source does not take is `bad_args` (`conflicting_flags`), never ignored. Everything here is pure: the views
are given, nothing is looked up."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import views
from .ids import BadId, parse as parse_id

KEYS = ("source", "in", "search", "quality", "group", "hidden", "verb_all", "plan")
SOURCES = ("library", "todo")
UPGRADE_ALL = "upgrade_all"  # Upgrade all: Same track for every parked upgrade To-do shows as possible
CHECK_DONE = "check_done"    # "Done, checked" for every check To-do lists
RENAME_ALL = "rename_all"    # Give it its clean name for every own clean AIFF whose name isn't clean, in a collection
DOWNLOAD_AGAIN = "download_again"    # Download again for every playlist song whose file is missing and gets it (issue 43)
REMOVE_MISSING = "remove_missing"    # Remove from library for every other song whose file is missing and gets it (issue 43)
VERB_ALL = (UPGRADE_ALL, CHECK_DONE, RENAME_ALL, DOWNLOAD_AGAIN, REMOVE_MISSING)
NO_ROWS = "No song is in that list, so there is nothing to do."

CONFLICT = "conflicting_flags"
ALL_IS_SAME_TRACK = "All of them is Same track only; name the songs to add them as new tracks."
NOT_A_LISTING = "A listing is a set of words: source, in, search, quality, group, hidden, verb_all or plan."


@dataclass(frozen=True)
class Listing:
    """A listing, checked. `view` and `key` (library) or `group` and `hidden` (to-do) are what the source's view takes."""
    source: str
    view: str = "all"
    key: str | None = None
    search: str = ""
    quality: str = "all"
    group: str = "all"
    hidden: bool = False
    verb_all: str | None = None
    plan: str | None = None  # `rename_all` only: the plan whose songs the run takes in too


def _text(listing: Mapping, name: str) -> str | None:
    value = listing.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadId("usage", f"{name} is a text.")
    return value


def collection(text: str) -> tuple[str, str | None]:
    """A collection id (`all`, `unlisted`, `playlist:<folder>`, `folder:<path>`, or a bare path) as the Library view's
    `(view, key)`. Raises `BadId` for text that names none."""
    found = parse_id(text, ("collection",))
    value = str(found.value)
    if value in ("all", "unlisted"):
        return value, None
    kind, _, key = value.partition(":")
    return kind, key


def parse(listing: object) -> Listing:
    """The listing, checked: unknown words, words of the other source and a verb's "all" with anything else are
    `BadId` (`bad_args`). The `in` of a folder is left as typed: the api turns a path into the folder's key."""
    if not isinstance(listing, Mapping):
        raise BadId("usage", NOT_A_LISTING)
    if unknown := sorted(set(listing) - set(KEYS)):
        raise BadId("usage", f"{unknown[0]} is not a word of a listing. {NOT_A_LISTING}")
    given = {k: v for k, v in listing.items() if v is not None}
    verb = _text(listing, "verb_all")
    if verb is not None:
        if verb not in VERB_ALL:
            raise BadId("usage", f"{verb} has no 'all' here: the ones that do are {', '.join(VERB_ALL)}.")
        if extra := sorted(set(given) - {"verb_all", *(("in", "plan") if verb == RENAME_ALL else ())}):
            raise BadId(CONFLICT, f"{extra[0]} narrows a listing; the 'all' of a verb is not one.")
        if verb == RENAME_ALL:
            view, key = collection(_text(listing, "in") or "all")
            return Listing("library", view=view, key=key, verb_all=verb, plan=_text(listing, "plan"))
        return Listing("todo", verb_all=verb)
    if "plan" in given:
        raise BadId(CONFLICT, "plan belongs to the 'all' of Rename; it narrows no listing.")
    source = _text(listing, "source") or ("todo" if "group" in given or "hidden" in given else "library")
    if source not in SOURCES:
        raise BadId("usage", f"source is {' or '.join(SOURCES)}, not {source}.")
    other = ("group", "hidden") if source == "library" else ("in", "search", "quality")
    if clash := [k for k in other if k in given]:
        raise BadId(CONFLICT, f"{clash[0]} is a word of {'to-do' if source == 'library' else 'the library'}, "
                              f"not of the {source} listing.")
    if source == "todo":
        group = _text(listing, "group") or "all"
        if group not in ("all", *views.TODO_GROUP_KEYS):
            raise BadId("usage", f"There is no to-do group called {group}. The groups are "
                                      f"{', '.join(views.TODO_GROUP_KEYS)}.")
        hidden = listing.get("hidden", False)
        if not isinstance(hidden, bool):
            raise BadId("usage", "hidden is true or false.")
        return Listing("todo", group=group, hidden=hidden)
    quality = _text(listing, "quality") or "all"
    if quality not in views.LIBRARY_FILTERS:
        raise BadId("usage", f"There is no quality filter called {quality}. The filters are "
                                  f"{', '.join(views.LIBRARY_FILTERS)}.")
    view, key = collection(_text(listing, "in") or "all")
    return Listing("library", view=view, key=key, search=_text(listing, "search") or "", quality=quality)


def _once(keys: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(keys))


def library_ids(answer: Mapping) -> list[str]:
    """The songs of a Library view the person can act on: every row of the view, a playlist's `also` rows included,
    that has a file (a playlist song that waits is no song to act on). Each once, in the order shown."""
    return _once(r["track_id"] for r in (*answer["rows"], *(answer.get("also") or ())) if r["file_state"] != "no_file")


def _tracks(item: Mapping) -> list[str]:
    """The songs a To-do item stands for: its own, or a check batch's tracks. A question or a duplicate group is no
    song (it carries a `pair`)."""
    if "pair" in item:
        return []
    if "batch" in item:
        return [t["track_id"] for t in item["batch"]["tracks"]]
    return [item["track_id"]]


def _group(answer: Mapping, key: str) -> list[Mapping]:
    return [i for g in answer["groups"] if g["key"] == key for i in g["items"]]


def todo_ids(answer: Mapping) -> list[str]:
    """The songs of the groups a To-do answer lists: a song in two groups is one song, a check batch its tracks."""
    return _once(t for g in answer["groups"] for i in g["items"] for t in _tracks(i))


def upgrade_all_ids(answer: Mapping) -> list[str]:
    """What Upgrade all runs: the Upgrade ready songs whose Same track can run (`same_track` is None), as the group's
    `all.n` counts them. `answer` is To-do's, without the hidden ones (a hidden song is not Upgrade all's)."""
    return _once(i["track_id"] for i in _group(answer, "upgrade_ready") if i["same_track"] is None)


def check_done_ids(answer: Mapping) -> list[str]:
    """What "Done, checked" for every check closes: the songs of the Check in rekordbox group, a batch's tracks."""
    return _once(t for i in _group(answer, "rekordbox_check") for t in _tracks(i))


def _missing_ids(answer: Mapping, action: str) -> list[str]:
    return _once(i["track_id"] for i in _group(answer, "missing_file")
                 if i["missing"]["action"] == action and i["missing"]["why_not"] is None)


def download_again_ids(answer: Mapping) -> list[str]:
    """What the "Select all" of the Missing files group asks Download again for: the group's songs whose action is
    Download again and that nothing keeps from it (`missing.why_not` is None), as the group's `all.download_again`
    counts them. `answer` is To-do's, without the hidden ones."""
    return _missing_ids(answer, "download_again")


def remove_missing_ids(answer: Mapping) -> list[str]:
    """What the "Select all" of the Missing files group asks Remove from library for (`all.remove`): as
    `download_again_ids`, for the songs whose action is Remove."""
    return _missing_ids(answer, "remove")
