"""`--since` (issue 39, design §5.3): the one reading of "from when", for `report list`, `batch list` and `history`.
`parse` turns what a person typed into a moment, `after` is the one comparison every list that takes `--since` uses.
Pure: the caller gives the clock."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from .. import words
from .ids import BadId

RELATIVE = re.compile(r"(\d+)([dh])")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _local(moment: datetime, zone_of: datetime) -> datetime:
    """`moment` as an aware time: one with no zone is local, in the zone of `zone_of` (the clock given) or, when the
    clock has none either, the machine's own (which knows its daylight saving)."""
    if moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=zone_of.tzinfo) if zone_of.tzinfo is not None else moment.astimezone()


def parse(text: str, now: datetime) -> datetime:
    """The moment `text` names, aware, in the local zone of `now` (a naive `now` is local). `today` and `yesterday` are
    the local midnight of that day; `3d` / `12h` (a whole number, 1 or more) is that long before `now`; `2026-11-20` is
    its local midnight; anything `datetime.fromisoformat` reads is that time (no zone: local). Else `BadId("usage")`
    with `words.BAD_SINCE`."""
    word = text.strip().lower()
    midnight = datetime.combine(now.date(), time())
    try:
        if word in ("today", "yesterday"):
            return _local(midnight - timedelta(days=1 if word == "yesterday" else 0), now)
        if m := RELATIVE.fullmatch(word):
            n = int(m.group(1))
            if n < 1:
                raise ValueError(text)
            earlier = now - (timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n))
            return earlier if earlier.tzinfo is not None else earlier.astimezone()
        if DATE.fullmatch(word):
            return _local(datetime.combine(date.fromisoformat(word), time()), now)
        return _local(datetime.fromisoformat(text.strip()), now)
    except (ValueError, OverflowError):  # `1000000d` is before year 1; a typed date or time can be out of range too
        raise BadId("usage", words.BAD_SINCE.format(text=text)) from None


def after(stamp: str | None, since: str | None) -> bool:
    """Whether `stamp` (an ISO time as the records keep it: no zone is local) is at or after `since` (an ISO time, what
    `parse` gave). True when there is no `since`, and when the stamp cannot be read or is out of range: a record that says
    nothing usable about its time is kept, not dropped. A `since` that is no time (a caller that skipped `parse`) raises
    `ValueError` with `words.BAD_SINCE`, whether or not a record is there to compare."""
    if since is None:
        return True
    try:
        cut = datetime.fromisoformat(since).astimezone()
    except (ValueError, OverflowError):
        raise ValueError(words.BAD_SINCE.format(text=since)) from None
    try:
        moment = datetime.fromisoformat(stamp).astimezone() if stamp else None
    except (ValueError, OverflowError):
        moment = None
    return moment is None or moment >= cut
