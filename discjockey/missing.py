"""Missing files (issue 43; plan `docs/2026-11-17-missing-files-plan.md` §4): the rules of the two actions the user can
take for a song whose file waits as missing (`models.file_missing`), and the words around them. The rules, the words
and the dry run (`preview`) are pure: no I/O, no clock (`today` comes in), so the views, the hub and the commands all
ask this one place. Only `download_again` and `remove` (the writes, at the bottom) touch the records, under the
caller's library lock.

- `action_for(key, e)`: the action follows the song, not a choice (D11): a song in a playlist gets Download again, any
  other song gets Remove from library.
- `why_not(key, e, state, action)`: the first reason the action can't run for the song now, else None.
- `will_words(action, upgrade_waiting)`: what the action does for this song (D9: a song with a parked upgrade gets
  that version put in, nothing is downloaded). The window shows these words and decides nothing.
- `view(...)`: the `missing` object of a To-do item; `detail_view(...)` the one of `track()` (the item's fields plus the
  `line` and the `hint`); `item_detail(...)` the item's one line.
- `preview(...)`: the dry run of both actions (`missing_files_preview`, `missing download|remove --dry-run`).
- `download_again(...)` / `remove(...)`: the two actions, one `ItemResult` per song. Neither touches a music file:
  Download again sets `file_gone` and nothing else; Remove (final, no undo) deletes the song's records and its parked
  upgrade's file in `Upgrades ready/`, Discjockey's own download, never anything else.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

from . import library, ops
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


# --- the dry run (plan §4.4) ---

def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary(action: str, plain: int, placed: int, removed: int, skipped: int, *, done: bool = False) -> str:
    """The one line the dry run, the job's result and the commands print. `plain`: songs that download again,
    `placed`: songs that get the parked better version instead (D9), `removed`: songs Remove takes out (all three count
    the songs that run), `skipped`: those that don't. `done`: the run is over (Remove then says "Removed")."""
    tail = f"; {skipped} {'is' if skipped == 1 else 'are'} skipped" if skipped else ""
    if action == REMOVE:
        if not removed:
            return f"Nothing to remove: {_plural(skipped, 'song is', 'songs are')} skipped."
        songs = f"{_plural(removed, 'song', 'songs')} from your library"
        return f"{'Removed' if done else 'Removes'} {songs}{tail}."
    if not plain and not placed:
        return f"Nothing to do: {_plural(skipped, 'song is', 'songs are')} skipped."
    if plain and placed:
        return (f"{_plural(plain, 'song downloads', 'songs download')} again and "
                f"{_plural(placed, 'gets', 'get')} the better version already waiting for "
                f"{'it' if placed == 1 else 'them'}, at your next sync{tail}.")
    if placed:
        return (f"{_plural(placed, 'song gets', 'songs get')} the better version already waiting for "
                f"{'it' if placed == 1 else 'them'} at your next sync; nothing is downloaded{tail}.")
    return f"{_plural(plain, 'song downloads', 'songs download')} again at your next sync{tail}."


def _counts(action: str, rows: Sequence[Mapping]) -> tuple[int, int, int, int]:
    """(plain, placed, removed, skipped) of rows that carry `will` and `upgrade_waiting`."""
    will = [r for r in rows if r["will"]]
    if action == REMOVE:
        return 0, 0, len(will), len(rows) - len(will)
    placed = sum(1 for r in will if r["upgrade_waiting"])
    return len(will) - placed, placed, 0, len(rows) - len(will)


def _checked(key: str, state: Mapping, action: str) -> tuple[Mapping, str | None]:
    """(the song's entry, why `action` can't run for it now). A key no song has is `not_missing`."""
    e = (state.get("tracks") or {}).get(key) or {}
    return e, why_not(key, e, state, action)


def preview(state: Mapping, keys: Sequence[str], action: str, place: Callable[[str], str] | None,
            today: date) -> dict:
    """What `action` would do for `keys`, answered before it runs (plan §4.4): `{action, items, n, skipped, words}`.
    One item per song, `{track_id, artist, title, place, since, will, reason, words, upgrade_waiting}`: `will` says
    whether the action runs for it now, `reason` (a `REASONS` key) and `words` why not otherwise, and `words` is
    `will_words` when it does; `upgrade_waiting` marks a song whose parked version Download again puts in instead of a
    download (D9) or Remove deletes (D10). `n` counts what will run, `skipped` the rest, `words` is the one line. Reads
    only. An unknown `action` is ValueError (the hub checks it first)."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    items = []
    for key in keys:
        e, reason = _checked(key, state, action)
        waiting = bool(e.get("upgrade"))
        items.append({"track_id": key, "artist": e.get("artist") or "", "title": e.get("title") or "",
                      "place": _was_in(e, place), "since": (e.get("missing_since") or "")[:10] or None,
                      "will": reason is None, "reason": reason,
                      "words": will_words(action, waiting) if reason is None else reason_words(reason, action),
                      "upgrade_waiting": waiting})
    n = sum(1 for i in items if i["will"])
    return {"action": action, "items": items, "n": n, "skipped": len(items) - n,
            "words": summary(action, *_counts(action, items))}


# --- the writes (plan §4.2, §4.3) ---

@dataclass(frozen=True)
class ItemResult:
    """One song of a run: `state` `done` | `skipped`; `reason` (a skip's `REASONS` key) and `words` (what was done, or
    the reason's sentence). `batches.ItemResult` carries rekordbox and file fields these actions never have."""
    track_id: str
    action: str
    state: str
    reason: str | None
    words: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def run_words(action: str, results: Sequence[ItemResult], state: Mapping | None = None) -> str:
    """The one line of a finished run (the job's `words`), in the dry run's grammar. `state`: the records the run
    started from, to tell the songs that got their parked version from those that download."""
    waiting = {r.track_id for r in results if r.state == "done"
               and (((state or {}).get("tracks") or {}).get(r.track_id) or {}).get("upgrade")}
    rows = [{"will": r.state == "done", "upgrade_waiting": r.track_id in waiting} for r in results]
    return summary(action, *_counts(action, rows), done=True)


def _skip(key: str, action: str, reason: str) -> ItemResult:
    return ItemResult(key, action, "skipped", reason, reason_words(reason, action))


def download_again(paths: library.Paths, keys: Sequence[str], *, now: Callable[[], datetime],
                   state: dict | None = None) -> list[ItemResult]:
    """Download again (plan §4.2) for `keys`, under the caller's library lock: the records are opened fresh (or the
    caller's `state`, opened under the same lock), `why_not` asked again per song (a song that changed since the click is
    `skipped` with its reason, never switched to the other action), and `file_gone` set to today for the rest, saved in
    one save and logged per song. Nothing else changes: the row, the parked upgrade and every answer stay until the
    sync places a file (D7): a download, or for a song with a parked upgrade the parked version (D9)."""
    state = library.open_state(paths) if state is None else state
    when, keys = now(), list(dict.fromkeys(keys))
    results: list[ItemResult] = []
    asked: list[tuple[dict, ItemResult]] = []
    for key in keys:
        e, reason = _checked(key, state, DOWNLOAD_AGAIN)
        if reason:
            results.append(_skip(key, DOWNLOAD_AGAIN, reason))
            continue
        results.append(ItemResult(key, DOWNLOAD_AGAIN, "done", None, will_words(DOWNLOAD_AGAIN, bool(e.get("upgrade")))))
        asked.append((dict(e), results[-1]))
        e["file_gone"] = when.date().isoformat()
    if asked:
        library.save_state(paths, state)
        for before, r in asked:
            ops.log_operation(paths, when, r.track_id, before, "download again", "done", r.words or "")
    return results


def remove(paths: library.Paths, keys: Sequence[str], *, now: Callable[[], datetime],
           state: dict | None = None) -> list[ItemResult]:
    """Remove from library (plan §4.3) for `keys`, under the caller's library lock; final, no undo (D10). Fresh records,
    `why_not` per song again (a changed song is `skipped` with its reason), then the songs' entries leave
    `state["tracks"]` in one save: `db.save` deletes the released row whose file isn't there, the song and its aliases,
    and the answers naming it. Only after the save has committed is each song's parked upgrade file deleted
    (`library.delete_parked`, which refuses any path outside `Upgrades ready/`: a record pointing anywhere else leaves
    that file alone), so a crash leaves at worst an orphan download, never a record naming a deleted file. No music file
    of the user's is touched: the song's own file is not there."""
    state = library.open_state(paths) if state is None else state
    when, keys = now(), list(dict.fromkeys(keys))
    results: list[ItemResult] = []
    gone: list[tuple[dict, ItemResult]] = []
    for key in keys:
        e, reason = _checked(key, state, REMOVE)
        if reason:
            results.append(_skip(key, REMOVE, reason))
            continue
        results.append(ItemResult(key, REMOVE, "done", None, will_words(REMOVE, bool(e.get("upgrade")))))
        gone.append((dict(e), results[-1]))
    if not gone:
        return results
    for _, r in gone:
        del state["tracks"][r.track_id]
    library.save_state(paths, state)
    for before, r in gone:
        note = r.words or ""
        up = before.get("upgrade")
        if up and up.get("file"):
            try:
                library.delete_parked(paths, up["file"])
            except ValueError:  # not Discjockey's download: the file stays where it is
                note += " Its parked file was not in Upgrades ready, so it was left alone."
        ops.log_operation(paths, when, r.track_id, before, "removed from library", "done", note)
    return results
