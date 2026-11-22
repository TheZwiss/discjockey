"""The generic printer (issue 39, plan v2 §3.1): turns any payload into a page, so a command needs no renderer of its
own. A headline (`message`, else the payload's `headline`, else its own `text`, else its first `*_text`), scalars as label/value rows (a
`<fact>` with a `<fact>_text` prints the words; the raw fact only with `--verbose`), lists of objects as tables in
payload order (`--limit` rows, default 200, `--offset`, a count line), nested objects as sections. A hand page names
the top-level fields it places; `rest(payload, placed)` prints the others under "More". Labels are field names in
words until the window's labels are carried over.

`leaves(value)` is every scalar of a payload as this printer writes it: the test T7' (every leaf of `data` occurs in
the text with `--verbose`) walks it. Pages may reorder and word, never drop."""
from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence

from .layout import Page, Row, Section, Table

DEFAULT_LIMIT = 200
TEXT = "_text"
VERBOSE_ONLY = frozenset({"rev"})  # a field with no words of its own that only `--verbose` prints (a record's revision)


def label(key: str) -> str:
    """A field name in words: `scanned_at` is "Scanned at"."""
    words = key.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def scalar(value: object) -> str:
    """A scalar as the printer writes it: yes / no, none, the number or the text as it is."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def cell(value: object) -> str:
    """Any value on one line: a list joined by commas, an object as `key: value` pairs."""
    if isinstance(value, Mapping):
        return ", ".join(f"{k}: {cell(v)}" for k, v in value.items()) or "none"
    if isinstance(value, Sequence) and not isinstance(value, str):
        return ", ".join(cell(v) for v in value) or "none"
    return scalar(value)


def leaves(value: object) -> Iterator[str]:
    """Every scalar inside `value`, as `scalar` writes it."""
    if isinstance(value, Mapping):
        for v in value.values():
            yield from leaves(v)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for v in value:
            yield from leaves(v)
    else:
        yield scalar(value)


def _is_object_list(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str) and bool(value) and all(
        isinstance(v, Mapping) for v in value)


def _headline(payload: Mapping, message: str | None) -> tuple[str | None, str | None]:
    """The headline and the payload key it came from (None when it is the message)."""
    if message:
        return message, None
    for key in ("headline", "text"):  # the answer's own sentence beats the first `<fact>_text` that happens to come first
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key], key
    for key, value in payload.items():
        if key.endswith(TEXT) and isinstance(value, str) and value:
            return value, key
    return None, None


def _columns(rows: Sequence[Mapping], verbose: bool) -> list[tuple[str, str]]:
    """(key, header) of a table in payload order; a fact with words shows its words (the raw fact: `--verbose`)."""
    keys: list[str] = []
    for row in rows:
        keys += [k for k in row if k not in keys]
    shown = [k for k in keys if verbose or (k + TEXT not in keys and k not in VERBOSE_ONLY)]
    return [(k, label(k[:-len(TEXT)]) if k.endswith(TEXT) and k[:-len(TEXT)] in keys and not verbose else label(k))
            for k in shown]


def _table(rows: Sequence[Mapping], *, verbose: bool, limit: int, offset: int,
           columns: Sequence[tuple[str, str]] | None = None) -> Table:
    page = list(rows[offset:] if limit == 0 else rows[offset:offset + limit])
    columns = list(columns) if columns is not None else _columns(rows, verbose)
    note = f"{len(page)} of {len(rows)} shown" + (" · --limit 0 for all" if len(page) < len(rows) else "")
    return Table([header for _, header in columns], [[cell(r.get(k)) if k in r else "" for k, _ in columns] for r in page],
                 note)


def table(rows: Sequence[Mapping], *, verbose: bool = False, limit: int = DEFAULT_LIMIT, offset: int = 0,
          columns: Sequence[tuple[str, str]] | None = None) -> Table:
    """A list of objects as a table, paged: all the keys in payload order, or `columns` ((key, header) pairs) when a
    hand page chooses them. The count line is the generic one."""
    return _table(rows, verbose=verbose, limit=limit, offset=offset, columns=columns)


def scalar_rows(payload: Mapping, skip: Collection[str] = (), *, verbose: bool = False) -> list[Row]:
    """The scalar fields of `payload` as label/value rows, in payload order (what the generic page prints under a
    heading); a hand page uses it for the fields it does not word itself."""
    return _rows(payload, skip, verbose)


def _rows(payload: Mapping, skip: Collection[str], verbose: bool) -> list[Row]:
    """The scalar fields of `payload` as rows, in payload order; short lists of plain values too."""
    out = []
    for key, value in payload.items():
        if key in skip or isinstance(value, Mapping) or _is_object_list(value) or (not verbose and key in VERBOSE_ONLY):
            continue
        if not verbose and not key.endswith(TEXT) and key + TEXT in payload:
            continue  # its words stand for it ("none" too: a fact with no words has none)
        name = label(key[:-len(TEXT)]) if key.endswith(TEXT) and key[:-len(TEXT)] in payload and not verbose else label(key)
        out.append(Row(name, cell(value)))
    return out


def _sections(payload: Mapping, heading: str | None, skip: Collection[str], verbose: bool, limit: int,
              offset: int) -> list[Section]:
    """The scalar rows under `heading`, then a section per nested object and a table per list of objects."""
    out = []
    rows = _rows(payload, skip, verbose)
    if rows:
        out.append(Section(heading, rows))
    for key, value in payload.items():
        if key in skip:
            continue
        name = f"{heading} › {label(key)}" if heading else label(key)
        if isinstance(value, Mapping) and value:
            out += _sections(value, name, (), verbose, limit, offset)
        elif _is_object_list(value):
            out.append(Section(name, table=_table(value, verbose=verbose, limit=limit, offset=offset)))
    return out


def page(payload: Mapping, *, message: str | None = None, verbose: bool = False, limit: int = DEFAULT_LIMIT,
         offset: int = 0) -> Page:
    """Any payload as a page."""
    headline, used = _headline(payload, message)
    return Page(headline, _sections(payload, None, {used} if used else (), verbose, limit, offset))


def rest(payload: Mapping, placed: Collection[str], *, heading: str | None = "More", verbose: bool = False,
         limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[Section]:
    """The fields of `payload` a hand page did not place (its top-level keys), as sections under `heading` ("More")."""
    return _sections({k: v for k, v in payload.items() if k not in placed}, heading, (), verbose, limit, offset)
