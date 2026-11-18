"""The track page (issue 39, design §4.2): `track show` prints the window's details panel as a page: the verdict (the
payload's `quality_line` and `quality_label`), the cutoff sentence (`cutoff_text`, the engine's words for where the
highs end), then the current file's facts under the window's own labels, and, for a song whose file waits as missing,
the engine's lines about it (`missing.line`, `hint`, `will`, `words`). Nothing is worded here: the page prints what
the payload carries. `generic.rest` prints every other field under "More"; the raw facts that the words above stand
for (`cutoff_hz`, `quality`, `status`, `source`) come back with `--verbose`."""
from __future__ import annotations

from collections.abc import Mapping

from . import generic
from .layout import Page, Row, Section

WORDED = {"track_id", "artist", "title", "quality_label", "quality_line", "cutoff_text", "format_line", "source_full",
          "source_format_line", "source_how", "playlists", "added", "path", "place", "file_state"}
RAW = {"cutoff_hz", "quality", "status", "source", "source_name"}  # facts the words above stand for: `--verbose`


def _rows(t: Mapping, labels: tuple[tuple[str, str], ...]) -> list[Row]:
    return [Row(label, generic.cell(t[key])) for key, label in labels if t.get(key) is not None]


def page(payload: Mapping, *, message: str | None = None, verbose: bool = False, limit: int = generic.DEFAULT_LIMIT,
         offset: int = 0) -> Page:
    t = payload.get("track")
    if not isinstance(t, Mapping):
        return generic.page(payload, message=message, verbose=verbose, limit=limit, offset=offset)
    quality = _rows(t, (("quality_label", "Rating"), ("quality_line", "Verdict"), ("cutoff_text", "Cutoff")))
    current = _rows(t, (("format_line", "Format"), ("source_full", "Source"), ("source_format_line", "Made from"),
                        ("source_how", "How it was found"), ("playlists", "Playlists"), ("added", "Added"),
                        ("place", "Folder"), ("path", "File"), ("file_state", "File state")))
    sections = [Section(None, [Row("Id", t["track_id"]), *quality])]
    if current:
        sections.append(Section("Current file", current))
    if isinstance(t.get("missing"), Mapping):  # a file that waits as missing: the engine's lines, not the raw keys
        sections.append(Section("Missing", _rows(t["missing"], (("line", "Not seen"), ("hint", "What to do"),
                                                                 ("will", "Will"), ("words", "Held back")))))
    placed = WORDED | (set() if verbose else RAW) | ({"missing"} if isinstance(t.get("missing"), Mapping) and not verbose
                                                      else set())  # `--verbose` prints its raw keys too
    sections += generic.rest(t, placed, verbose=verbose, limit=limit, offset=offset)
    return Page(f"{t['artist']} - {t['title']}", sections)
