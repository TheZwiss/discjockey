"""The To-do page (issue 39, design §4.2): `todo list`, `upgrade list` and `check list` print the same page, the window's
groups under the window's own names (the payload's `label` and `hint`), each a table of its items with their ids. It
places what the window shows of an item: the quality words, and `detail` (the payload's own line: "Waits for rekordbox
to be closed" for an upgrade that waits, "next try in 3 days", the question's words). A check also says what to do in
rekordbox (`check.text`); a missing file what Download again or Remove would do for it (`missing.will`) and, when
something holds it back, why (`missing.words`). Whatever the page does not place is printed by `generic.rest`; `--verbose` prints every
field of every item as the generic table does."""
from __future__ import annotations

from collections.abc import Mapping

from . import generic
from .layout import Page, Row, Section

ITEM_COLUMNS = (("track_id", "Id"), ("artist", "Artist"), ("title", "Title"), ("quality_label", "Quality"),
                ("detail", "Detail"))
HIDDEN_COLUMN = ("hidden", "Hidden")
CHECK_COLUMN = ("what_to_do", "What to do")
WILL_COLUMN, HELD_BACK_COLUMN = ("will", "Will"), ("held_back", "Held back")  # a missing file's `missing.will` and `missing.words`
GROUP_KEYS = ("key", "label", "hint", "items")  # a group's own fields besides what its items carry


def _item(item: Mapping) -> dict:
    """An item's placed fields: the payload's own words, and for a check what to do in rekordbox. A batch of checks is
    one item whose own key (`batch:<n>`) no command takes: it shows the id `check done --batch` takes and says so."""
    placed = {**{key: item.get(key) for key, _ in ITEM_COLUMNS}, "hidden": item.get("hidden"),
              "what_to_do": (item.get("check") or {}).get("text"), "will": (item.get("missing") or {}).get("will"),
              "held_back": (item.get("missing") or {}).get("words")}
    batch = item.get("batch")
    if batch and batch.get("aiff_id"):
        placed["track_id"] = batch["aiff_id"]
        placed["detail"] = f"{item.get('detail')} · {batch.get('size')} tracks · check done --batch {batch['aiff_id']}"
    return placed


def _group(group: Mapping, *, verbose: bool, show_hidden: bool, limit: int, offset: int) -> list[Section]:
    items = group.get("items") or []
    if verbose:
        rows = generic.scalar_rows(group, ("items", "label", "hint"), verbose=True)
        return [Section(group.get("label"), rows, generic.table(items, verbose=True, limit=limit, offset=offset),
                        lead=group.get("hint")),
                *generic.rest({k: v for k, v in group.items() if isinstance(v, Mapping)}, (), heading=group.get("label"),
                              verbose=True)]  # what a group's own objects say (`all`, `stopped`): scalar_rows skips them
    columns = [*ITEM_COLUMNS, *([HIDDEN_COLUMN] if show_hidden else []),
               *([CHECK_COLUMN] if any((i.get("check") or {}).get("text") for i in items) else []),
               *([WILL_COLUMN] if any(i.get("missing") for i in items) else []),
               *([HELD_BACK_COLUMN] if any((i.get("missing") or {}).get("words") for i in items) else [])]
    sections = [Section(group.get("label"), table=generic.table([_item(i) for i in items], columns=columns, limit=limit,
                                                                offset=offset), lead=group.get("hint"))]
    for item in items:  # a batch of checks lists its own songs, each with the id its commands take
        batch = item.get("batch")
        if batch and batch.get("aiff_id"):
            sections.append(Section(batch["aiff_id"], table=generic.table([_item(t) for t in batch.get("tracks") or []],
                                                                         columns=columns)))
    # the group's own facts (Upgrade all's counts, the stopped batch that waits for Resume), under the group's name;
    # `all.label` is the window's link text ("Select all · 5"), not a fact: `--verbose` and `--json` keep it
    own = {k: v for k, v in group.items() if k not in GROUP_KEYS and v is not None}
    if isinstance(own.get("all"), Mapping):
        own["all"] = {k: v for k, v in own["all"].items() if k != "label"}
    sections += generic.rest(own, (), heading=group.get("label"), verbose=False, limit=limit, offset=offset)
    return sections


def page(payload: Mapping, *, message: str | None = None, verbose: bool = False, limit: int = generic.DEFAULT_LIMIT,
         offset: int = 0) -> Page:
    """The To-do answer as a page: a summary, then a section per group. `--verbose` leaves the summary to `rest`
    (the raw counts) and prints every field of every item."""
    chips = payload.get("chips") or {}
    placed = {"groups"} if verbose else {"groups", "chips", "check_tracks", "sub", "hidden_count", "show_hidden", "empty",
                                         "empty_text"}
    sections = []
    if not verbose:
        rows = [Row("To-do items", generic.scalar(chips.get("all"))),
                Row("Checks open", generic.scalar(payload.get("check_tracks"))),
                Row("Hidden", generic.scalar(payload.get("hidden_count")))]
        if payload.get("sub"):  # the window's header line, worded by the engine
            rows.insert(1, Row("Summary", " · ".join(payload["sub"])))
        if payload.get("empty"):
            rows.append(Row("Nothing to show", generic.scalar(payload.get("empty_text"))))
        sections.append(Section(None, rows))
    for g in payload.get("groups") or []:
        sections += _group(g, verbose=verbose, show_hidden=bool(payload.get("show_hidden")), limit=limit, offset=offset)
    sections += generic.rest(payload, placed, verbose=verbose, limit=limit, offset=offset)
    return Page(message, sections)
