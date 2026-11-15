"""The words the engine owns for the command line (issue 39, design §8.3): the steps only a person can do after a
change that rekordbox does not notice by itself. The window still builds its own numbered steps from the same facts
(`decisionModel.ts`); phase 6 splits these into numbered steps and takes that copy away. A later group adds the words
of the other answers here.

`person_steps` turns one open rekordbox check into the steps of `HubApi.todo`'s `check.person_steps`: the step's `id`
and `then` come from `outcomes.STEPS`, its `say` is the engine's own sentence for the check (`report.check_text`, with
the USB step where the check has one: `report.usb_step`). The track's name is its key: `check done <key>` is the next
command."""
from __future__ import annotations

from . import report
from .hub.outcomes import person_step
from .rekordbox.preview import REASON_WORDS

REKORDBOX_STATE = {"ready": "rekordbox's library can be read", "none": "no rekordbox library on this Mac",
                   "unreadable": "rekordbox's library can't be read"}
REKORDBOX_PROBLEM = {
    "unclean": "rekordbox didn't close normally last time; open rekordbox, quit it, and try again",
    "busy": "rekordbox is open and its library is busy right now",
    "key": "Discjockey can't unlock rekordbox's library",
    "db_version": "rekordbox's library is a version Discjockey doesn't know",
    "schema": "rekordbox's library is laid out differently than Discjockey expects",
}

SWAP_REASONS = ("swapped", "repointed", "converted")  # the old rekordbox track keeps its file: Reload Tag
ADDED_REASON = "added_as_new"                          # a new file: the old rekordbox track is pointed at it by hand


def rekordbox_words(state: str, problem: str | None) -> tuple[str, str | None]:
    """(what state rekordbox's library is in, what is wrong with it or None) in words, for `rekordbox_status` and the
    preview's `rekordbox` part."""
    return REKORDBOX_STATE[state], REKORDBOX_PROBLEM[problem] if problem else None


def check_sentence(check: dict) -> str:
    """What to do in rekordbox for `check` (a `rekordbox_check` record), as one sentence: `report.check_text`, then the
    USB step when this check has one (a repointed or converted file that rekordbox has tracks of)."""
    usb = report.usb_step(check)
    return f"{report.check_text(check)} {usb}" if usb else report.check_text(check)


def person_steps(track_id: str, check: dict | None, new_path: str | None = None) -> list[dict]:
    """The steps for the open check of `track_id`: an added file (New track) is `step:relocate_new`, with the new
    file's absolute path (`new_path`) at the end of its sentence; a swap, Same track or Convert is `step:reload_tag`.
    Every step's `then` is `check done <track_id>`. A check that leaves the person nothing to do (a clean name, the
    wrong song) has none."""
    check = check or {}
    reason = check.get("reason")
    if reason == ADDED_REASON:
        name, say = "relocate_new", check_sentence(check) + (f" The new file: {new_path}" if new_path else "")
    elif reason in SWAP_REASONS:
        name, say = "reload_tag", check_sentence(check)
    else:
        return []
    return [{**person_step(name, tracks=track_id), "say": say}]


TIMING_WORDS = {
    "no_rekordbox": "no rekordbox library on this Mac, so nothing to line up with",
    "not_in_rekordbox": "not in your rekordbox collection",
    "format": "this format has no delay",
    "no_cues": "no cues or beat grid in rekordbox to keep in place",
    "measured": "measured",
    "not_analysed": "rekordbox hasn't analysed it yet",
    "timing": "couldn't be measured exactly",
    "unreadable": "rekordbox's library can't be read",
}
WRITING_WORDS = "Discjockey is changing your rekordbox library in another window or the Terminal; try again when it is done"


def preview_words(out: dict) -> dict:
    """`preview`'s answer with the console's words beside the facts (`<fact>_text`, the generic page prints them): what
    each action would do, how the timing came out, what state rekordbox's library is in."""
    rb = out["rekordbox"]
    state_text, problem_text = rekordbox_words(rb["state"], rb["problem"])
    return {**out,
            "rekordbox": {**rb, "state_text": state_text, "problem_text": problem_text,
                          **({"writing_text": WRITING_WORDS} if rb.get("writing") else {})},
            "timing": {**out["timing"], "result_text": TIMING_WORDS[out["timing"]["result"]]},
            "eligible": {k: v for action, reason in out["eligible"].items() for k, v in (
                (action, reason), (f"{action}_text", "possible" if reason is None else REASON_WORDS[reason]))}}
