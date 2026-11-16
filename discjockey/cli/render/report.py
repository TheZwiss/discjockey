"""The run report's page (issue 39, design §4.2): `report show` prints the generic page, except that the report's id is
printed once. The run summary carries it twice, bare (`run_id`, the file's stem) and as the id commands take (`id`,
`report:<stamp>`); the page keeps `id`, and `--verbose` prints both."""
from __future__ import annotations

from collections.abc import Mapping

from . import generic
from .layout import Page

HIDDEN = ("run_id",)  # the same fact as `id`, without its kind


def page(payload: Mapping, *, message: str | None = None, verbose: bool = False, limit: int = generic.DEFAULT_LIMIT,
         offset: int = 0) -> Page:
    """The report as the generic page, without the fields the id already says (all of them with `--verbose`)."""
    shown = payload if verbose else {key: ({k: v for k, v in value.items() if k not in HIDDEN}
                                           if isinstance(value, Mapping) else value) for key, value in payload.items()}
    return generic.page(shown, message=message, verbose=verbose, limit=limit, offset=offset)
