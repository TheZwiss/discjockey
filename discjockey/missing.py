"""Missing files (issue 43; plan `docs/2026-11-17-missing-files-plan.md` §4): the rules of the two actions the user can
take for a song whose file waits as missing (`models.file_missing`), and the words around them. Pure: no I/O, no clock
(`today` comes in), so the views, the hub and the commands all ask this one place.

- `action_for(key, e)`: the action follows the song, not a choice (D11): a song in a playlist gets Download again, any
  other song gets Remove from library.
- `why_not(key, e, state, action)`: the first reason the action can't run for the song now, else None.
- `will_words(action, upgrade_waiting)`: what the action does for this song (D9: a song with a parked upgrade gets
  that version put in, nothing is downloaded). The window shows these words and decides nothing.
- `view(...)`: the `missing` object of a To-do item; `detail_view(...)` the one of `track()` (the item's fields plus the
  `line` and the `hint`); `item_detail(...)` the item's one line.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from .models import file_missing

DOWNLOAD_AGAIN = "download_again"
REMOVE = "remove"
ACTIONS = (DOWNLOAD_AGAIN, REMOVE)
ACTION_WORDS = {DOWNLOAD_AGAIN: "Download again", REMOVE: "Remove from library"}  # the buttons' words, without the dots

# `why_not`'s reasons, in the order they are tried, with their words (plan §5.4). `wrong_action` names the action the
# song gets instead (`reason_words`).
REASONS = {
    "not_missing": "Its file is back.",
    "wrong_action": "This song gets {other} instead.",
    "found_twice": "Its file is in several places now: keep one and it links again.",
    "never": "You chose Never download for it.",
    "check_open": "Its rekordbox check is still open: finish it first.",
    "asked": "You asked for it already: it happens at your next sync.",
}

WILL = {
    "download": "Downloads again at your next sync",
    "place": "Gets the better version already waiting for it at your next sync; nothing is downloaded",
    "remove": "Removed from your library",
}

COMES_BACK = "Put the file back in any watched folder and it links again with everything it had."
HINT_DOWNLOAD = f"{COMES_BACK} Or download it again at your next sync."
HINT_PLACE = (f"{COMES_BACK} Or press Download again: the better version already waiting for it goes in at your next "
              "sync, and nothing is downloaded.")
HINT_REMOVE = f"{COMES_BACK} Or remove the song from your library."
HINT_REMOVE_PARKED = " Its better version waiting in Upgrade ready goes with it."
HINT_TWICE = "Delete or move away the copies you don't want; the one left links again."


def other_action(action: str) -> str:
    return REMOVE if action == DOWNLOAD_AGAIN else DOWNLOAD_AGAIN


def action_for(key: str, e: Mapping) -> str:
    """`download_again` for a song in a playlist (an own key linked to a playlist song included: `in_playlists`), else
    `remove` (D11). A playlist song gets no Remove: the next sync would add it again and download it."""
    return DOWNLOAD_AGAIN if e.get("in_playlists") else REMOVE


def why_not(key: str, e: Mapping, state: Mapping, action: str) -> str | None:
    """Why `action` can't run for song `key` now (a `REASONS` key), else None. The first that applies:
    `not_missing` (its file is back, or it has no file row), `wrong_action` (the other action is this song's),
    `found_twice` (in several places; Download again only: Remove may still run for an own song), `never` (Download
    again only), `check_open` (an open rekordbox check; Remove only: its undo store would be left behind), `asked`
    (`file_gone` already set; Download again only)."""
    if not file_missing(e):
        return "not_missing"
    if action != action_for(key, e):
        return "wrong_action"
    if action == DOWNLOAD_AGAIN:
        if key in (state.get("ambiguous") or {}):
            return "found_twice"
        if key in (state.get("never") or {}):
            return "never"
        if e.get("file_gone"):
            return "asked"
    elif e.get("rekordbox_check"):
        return "check_open"
    return None


def reason_words(reason: str, action: str) -> str:
    """The words of a `why_not` reason for `action` (`wrong_action` names the action the song gets instead)."""
    return REASONS[reason].format(other=ACTION_WORDS[other_action(action)])


def will_words(action: str, upgrade_waiting: bool) -> str:
    """What `action` does for a song: the one sentence the item, the dry run and the selection panel show. Which of the
    two Download again outcomes happens is the engine's decision (D9: the parked version goes in, nothing is
    downloaded), so the window gets the words, never the rule."""
    if action == REMOVE:
        return WILL["remove"]
    return WILL["place"] if upgrade_waiting else WILL["download"]


def _was_in(e: Mapping, place: Callable[[str], str] | None) -> str:
    path = e.get("path")
    return place(path) if place is not None and path else ""


def _since(e: Mapping, today: date) -> str:
    """The day of the first scan that missed the file, in few words ("12 Nov"). `words` imports `hub.outcomes`, which
    reads this module's reasons, so it is imported here."""
    from .words import short_day
    return short_day(date.fromisoformat(e["missing_since"][:10]), today)


def _candidates(key: str, state: Mapping) -> list[str]:
    return list((state.get("ambiguous") or {}).get(key) or [])


def item_detail(key: str, e: Mapping, state: Mapping, place: Callable[[str], str] | None, today: date) -> str:
    """The one line of a To-do item: "Missing since 12 Nov · was in Techno 2019"; a song found in several places: "In 2
    places now · keep one and it links again"."""
    found = _candidates(key, state)
    if found:
        return f"In {len(found)} places now · keep one and it links again"
    since = _since(e, today)
    where = _was_in(e, place)
    return f"Missing since {since} · was in {where}" if where else f"Missing since {since}"


def view(key: str, e: Mapping, state: Mapping, place: Callable[[str], str] | None, today: date) -> dict | None:
    """The `missing` object of an item (plan §5.2), None when the song's file isn't missing: `since` (the ISO day of the
    first scan that missed it), `place` (where it was, the Folder column's words), `action`, `why_not` and its
    `words`, `will` (what the action does for this song) and `upgrade_waiting` (a parked better version: Download
    again puts it in instead of a download, Remove deletes it). `today` is unused here (`since` is the ISO day, the
    line words it); it keeps plan §4.1's signature, the one `item_detail` and `detail_view` share."""
    if not file_missing(e):
        return None
    action = action_for(key, e)
    reason = why_not(key, e, state, action)
    waiting = bool(e.get("upgrade"))
    return {"since": e["missing_since"][:10], "place": _was_in(e, place), "action": action, "why_not": reason,
            "words": reason_words(reason, action) if reason else None, "will": will_words(action, waiting),
            "upgrade_waiting": waiting}


def _line(key: str, e: Mapping, state: Mapping, place: Callable[[str], str] | None, today: date) -> str:
    found = _candidates(key, state)
    if found:
        where = [place(p) if place is not None else p for p in found]
        names = f"{', '.join(where[:-1])} and {where[-1]}" if len(where) > 1 else where[0]
        return f"Found in {len(found)} places: {names}."
    since = _since(e, today)
    where = _was_in(e, place)
    return f"Not seen since {since}. It was in {where}." if where else f"Not seen since {since}."


def _hint(key: str, e: Mapping, state: Mapping, action: str) -> str:
    if _candidates(key, state):
        return HINT_TWICE
    waiting = bool(e.get("upgrade"))
    if action == DOWNLOAD_AGAIN:
        return HINT_PLACE if waiting else HINT_DOWNLOAD
    return HINT_REMOVE + (HINT_REMOVE_PARKED if waiting else "")


def detail_view(key: str, e: Mapping, state: Mapping, place: Callable[[str], str] | None, today: date) -> dict | None:
    """`track()`'s `missing` (plan §5.3): `view`'s fields plus `line` ("Not seen since 12 Nov. It was in Techno 2019.";
    in several places: "Found in 2 places: Techno 2019 and Old crates.") and `hint` (what can be done, by action)."""
    v = view(key, e, state, place, today)
    if v is None:
        return None
    return {**v, "line": _line(key, e, state, place, today), "hint": _hint(key, e, state, v["action"])}
