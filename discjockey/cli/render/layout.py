"""The text page (issue 39, design §4.2): a headline, sections with label/value rows, and tables, rendered as plain
text. Ids, `rev` and raw numbers that have words appear only with `--verbose`; that is the caller's rule, this module
only lays out what it is given. Colour is only for a terminal that wants it (`use_color`: `--no-color` and `NO_COLOR`
turn it off)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

BOLD = "\033[1m"
RESET = "\033[0m"


@dataclass
class Row:
    label: str
    value: str


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]
    note: str | None = None  # the count line under it ("12 of 340 shown · --limit 0 for all")


@dataclass
class Section:
    heading: str | None
    rows: list[Row] = field(default_factory=list)
    table: Table | None = None
    lead: str | None = None  # a line under the heading (a group's hint)


@dataclass
class Page:
    headline: str | None
    sections: list[Section] = field(default_factory=list)


def use_color(stream, *, no_color: bool = False, environ=None) -> bool:
    """Whether to colour what is printed on `stream`: a terminal, and neither `--no-color` nor `NO_COLOR` said no."""
    env = os.environ if environ is None else environ
    return bool(not no_color and not env.get("NO_COLOR") and getattr(stream, "isatty", lambda: False)())


def _table_lines(table: Table) -> list[str]:
    widths = [len(c) for c in table.columns]
    for row in table.rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(table.columns, widths)).rstrip()]
    lines += ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in table.rows]
    if table.note:
        lines.append(table.note)
    return lines


def render(page: Page, *, color: bool = False) -> str:
    """The page as text: headline, then each section (heading, label/value rows aligned, table) separated by a blank
    line."""
    blocks: list[list[str]] = []
    if page.headline:
        blocks.append([f"{BOLD}{page.headline}{RESET}" if color else page.headline])
    for section in page.sections:
        lines = [section.heading] if section.heading else []
        if section.lead:
            lines.append(section.lead)
        if section.rows:
            width = max(len(r.label) for r in section.rows)
            lines += [f"{r.label.ljust(width)}  {r.value}".rstrip() for r in section.rows]
        if section.table is not None:
            lines += _table_lines(section.table)
        if lines:
            blocks.append(lines)
    return "\n\n".join("\n".join(b) for b in blocks)
