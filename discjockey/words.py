"""The words the engine owns for the command line (issue 39, design §8.3): the steps only a person can do after a
change that rekordbox does not notice by itself. The window still builds its own numbered steps from the same facts
(`decisionModel.ts`); phase 6 splits these into numbered steps and takes that copy away. A later group adds the words
of the other answers here.

`person_steps` turns one open rekordbox check into the steps of `HubApi.todo`'s `check.person_steps`: the step's `id`
and `then` come from `outcomes.STEPS`, its `say` is the engine's own sentence for the check (`report.check_text`, with
the USB step where the check has one: `report.usb_step`). The track's name is its key: `check done <key>` is the next
command."""
from __future__ import annotations

from datetime import date

from . import convert, rbstep, report
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

# a dry run plans on the last scan; this is what it says when a folder has changed since (design §7.1)
SCAN_OLDER = "Library/ or a watched folder changed after the last scan, so this plan is on the files as that scan saw them."

# a collection (`--in`) that is not there (`HubApi.resolve("collection", ...)`; the words the console's `convert --in` had)
# One line for each noun of the command line, for the short `help` list (tests/test_cli_housekeeping.py: a noun with no
# words cannot ship)
NOUN_WORDS = {
    "aiff": "Make files AIFF and give them clean names.",
    "batch": "The batches Discjockey made: list, show, carry on or undo one.",
    "check": "The checks to do in rekordbox after a file changed.",
    "folder": "The folders Discjockey watches for your own files.",
    "library": "Your library: read it again, read file facts.",
    "missing": "Songs whose file is missing: list them, download again or remove from your library.",
    "rekordbox": "rekordbox's library: its state, what a change would do, its backups.",
    "report": "The reports of past syncs.",
    "settings": "What Settings holds, and changing it.",
    "sync": "The sync.",
    "todo": "Your to-do list.",
    "track": "One song: find it, show it, undo its last step.",
    "upgrade": "Better versions waiting: list, put in, throw away.",
    "job": "Long runs: list, show, follow, wait for, stop.",
}

NO_PLAYLIST = "No playlist called “{name}”."
NO_SONG = "Your library has no song {key}. `track find <words>` finds a song's id."
NO_REPORT_YET = "There is no run report yet."
NO_REPORT = "There is no report {stamp}. `report show last` shows the newest; a sync prints the id of its report."
NO_FOLDER = "No folder at {path}."
NOT_WATCHED = "{path} is not one of the watched folders."
LIBRARY_NOT_REMOVABLE = "{path} is your Library: it is always watched and cannot be removed."
BAD_FOLDER = "A folder is its path, or folder:<path>."
BAD_COLLECTION = "A collection is all, unlisted, playlist:<name> or folder:<path>."

# file facts (`library facts`, and the dry runs that read a few in memory: design §5.3, §7.1)
FACTS_MISSING = ("{n} files have not been read yet, which is more than can be read at once ({most} at most). "
                 "Read them once first, then try again.")
LOSSY_NOTE = "{n} of these {are} lossy: an AIFF made from them sounds the same and takes 5–10 times the space."
FACTS_READ = "Read the facts of {n} file{s}."
FACTS_NONE = "Nothing to read: Discjockey knows the facts of every file already."
FACTS_WOULD = "{n} file{s} would be read."
FACTS_UNREADABLE = "{n} file{s} could not be read and {stay} without facts."

# `rekordbox restore` (design §7.4): why a restore was refused (`RestoreRefused.reason`), what it says when done, and what
# it says of the tracks that now point at files Discjockey moved
RESTORE_REFUSED = {
    "no_rekordbox": "There is no rekordbox library on this Mac, so nothing was changed.",
    "not_found": "There is no backup with that name; `rekordbox backups` lists them. Nothing was changed.",
    "damaged": "This backup is damaged (its copy of rekordbox's library is not the one its notes name), so nothing "
               "was changed.",
    "other_library": "This backup was made from another rekordbox library than this Mac's, so nothing was changed.",
    "rekordbox_open": convert.REKORDBOX_OPEN,
    "unclean": rbstep.REFUSED["unclean"],
    "changed": "rekordbox's library changed while it was being saved, so nothing was changed. Try again.",
}
RESTORED = "Restored rekordbox's library from {backup}. Your library as it was is saved as {saved}."
MISSING_AFTER = ("{n} of your rekordbox tracks now point at files that Discjockey has since moved to Superseded/. "
                 "Undo those batches first (`batch undo`), or Relocate them in rekordbox.")
WOULD_MISSING = ("{n} of your rekordbox tracks would point at files that Discjockey has since moved to Superseded/. "
                 "Undo those batches first (`batch undo`), or Relocate them in rekordbox.")

# Auto-upgrade, the sync's last phase (`sync run --auto-upgrade-only`; plan stage C §3). `before_start_line` is the Sync page's
# line before a start while rekordbox is open, `AUTO_PLAN_LINE` the one it shows while rekordbox is closed (both are
# built by the window itself in `planModel.ts` today; phase 6 takes that copy away), `waiting_line` what the phase says
# when it meets rekordbox open at the end of a sync, `AUTO_UPGRADE_OFF` what the phase alone says with the switch off.
AUTO_UPGRADE_OFF = "Auto-upgrade is off, so nothing was moved."
AUTO_UPGRADE_NOTHING = "No upgrade was waiting, so nothing was moved."


def before_start_line(n: int) -> str:
    """Plan stage C §3's Sync before-start Hint: said before a sync starts (the Sync page, the console's plan). The
    check happens when the phase begins, at the end of the sync, so rekordbox may still be quit until then. The phase
    itself, which meets rekordbox open at that moment, says `waiting_line` instead."""
    return (f"rekordbox is open: quit it before the sync ends, so the sync can put {n} "
            f"upgrade{'s' if n != 1 else ''} in place.")


def auto_plan_line(n: int) -> str:
    """The Sync page's one-line Hint under Start while rekordbox is closed: what the sync will do at its end."""
    return f"{n} {'upgrade goes' if n == 1 else 'upgrades go'} in at the end; cues stay."


def waiting_line(n: int) -> str:
    """What the phase says when it meets rekordbox open at the end of a sync (the same words as the summary line's
    clause for n = 0): nothing was upgraded, `n` upgrades wait."""
    return f"{n} upgrade{' waits' if n == 1 else 's wait'} for rekordbox to be closed."


def place_plan_line(n: int, waits: bool = False, name: str | None = None) -> str:
    """The Sync page's before-start clause for the placements (issue 43, D9, plan §5.4): songs the user asked to download
    again whose file is missing and whose better version is parked get it at the end of the sync, with the Auto-upgrade
    switch off too. `waits`: rekordbox is open, so they go in once it is closed. `name`: the one song's "Artist – Title"
    when n is 1 (the clause names it; with several it keeps the count)."""
    if n == 1 and name:
        songs = f"{name} gets its better version"
    else:
        songs = "1 missing song gets its better version" if n == 1 else f"{n} missing songs get their better version"
    return f"{songs} at the end of the sync{', once rekordbox is closed' if waits else ''}."


def song_name(e: dict) -> str:
    """A song's "Artist – Title" (the house dash) for a line that names it."""
    return f"{e.get('artist') or '?'} – {e.get('title') or '?'}"


def placing_line(n: int) -> str:
    """What the phase says as it starts the placements."""
    return f"Putting in the better version of {n} missing song{'s' if n != 1 else ''} at the end of the sync..."


def place_waiting_line(n: int) -> str:
    """What the phase says when it meets rekordbox open for the placements (`waiting_line`'s sibling)."""
    return (f"{n} missing song{' waits' if n == 1 else 's wait'} for rekordbox to be closed to get "
            f"{'its' if n == 1 else 'their'} better version.")


# Settings (`settings show`, `settings set auto-upgrade`): the names the Settings page gives its two switches, and what
# a change says
AUTO_UPGRADE_LABEL = "Upgrade automatically when I sync"
LIKED_MUSIC_LABEL = "Read my Liked music"
AUTO_UPGRADE_SET = {True: "Upgrade automatically when I sync: on. Nothing moves until the next sync.",
                    False: "Upgrade automatically when I sync: off. The upgrades that are ready wait in your to-do list."}

# Watched folders (`folder add`, `folder remove`): the words of the window's remove question (`removeWords`), and what the
# command says once the folder is no longer watched
REMOVAL_FORGETS = "Discjockey forgets its {files}. The files stay where they are."
REMOVAL_AGAIN = {1: "1 song from your playlists had its only copy there. It will be downloaded again at the next sync.",
                 None: "{n} songs from your playlists had their only copy there. They will be downloaded again at the "
                       "next sync."}
REMOVED = "Stopped watching {name}."


def removal_words(files: int, redownload: int) -> str:
    """What removing a watched folder takes away: its files (they stay on disk) and the playlist songs that download
    again (the window's `removeWords` body)."""
    out = [REMOVAL_FORGETS.format(files=f"{files:,} file{'s' if files != 1 else ''}")]
    if redownload > 0:
        out.append(REMOVAL_AGAIN[1] if redownload == 1 else REMOVAL_AGAIN[None].format(n=f"{redownload:,}"))
    return " ".join(out)


# what a Convert / Rename run says it did (the console's words, `aiff convert` and `aiff rename`)
AIFF_LEFT = "{n} left as they are."


def aiff_summary(results: list[dict], done: int, not_done: int) -> str:
    """The one line of an AIFF batch's result: "Made 2 files AIFF, gave 1 file its clean name." for the items that went
    through, "N left as they are." for the ones that did not (a song a plan or the run left as it is, a failed one)."""
    made = sum(1 for r in results if r.get("state") == "done" and r.get("action") == "convert")
    named = sum(1 for r in results if r.get("state") == "done" and r.get("action") == "rename")
    plural = lambda n: f"{n} file{'s' if n != 1 else ''}"  # noqa: E731
    parts = ([f"made {plural(made)} AIFF"] if made else []) + (
        [f"gave {plural(named)} {'its' if named == 1 else 'their'} clean name"] if named else [])
    lines = [f"{parts[0][:1].upper()}{parts[0][1:]}{''.join(', ' + p for p in parts[1:])}."] if parts else (
        [f"{done} done."] if done else [])
    return " ".join([*lines, *([AIFF_LEFT.format(n=not_done)] if not_done else [])])


SWAP_REASONS = ("swapped", "repointed", "converted")  # the old rekordbox track keeps its file: Reload Tag
ADDED_REASON = "added_as_new"                          # a new file: the old rekordbox track is pointed at it by hand
PLACED_REASON = "placed_missing"                       # Download again put the parked version in for a missing file


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
    file's absolute path (`new_path`) at the end of its sentence; a swap, Same track or Convert is `step:reload_tag`
    while rekordbox's text is still to be reloaded (`reload_tag`, true for a record without it), else `step:look`:
    Discjockey wrote rekordbox's text itself, and a needless Reload Tag would replace the names the person changed.
    Every step's `then` is `check done <track_id>`. A check that leaves the person nothing to do (a clean name, the
    wrong song) has none."""
    check = check or {}
    reason = check.get("reason")
    if reason == ADDED_REASON:
        name, say = "relocate_new", check_sentence(check) + (f" The new file: {new_path}" if new_path else "")
    elif reason == PLACED_REASON:
        # a placement for a missing file (plan §5.4): the track was pointed at it (its text columns were never written,
        # so a Reload Tag would replace the names the person changed: `look`), or it is a different edit that rekordbox
        # takes as a new file (`relocate_new`), or nothing in rekordbox plays it by name (`look`)
        new_file = not check.get("repointed") and check.get("aligned", True) and check.get("match") not in ("exact", "shifted")
        name, say = ("relocate_new" if new_file else "look"), check_sentence(check)
        if new_file and new_path:
            say += f" The new file: {new_path}"
    elif reason in SWAP_REASONS:
        name, say = ("reload_tag" if check.get("reload_tag", True) is not False else "look"), check_sentence(check)
    else:
        return []
    return [{**person_step(name, tracks=track_id), "say": say}]


# The To-do page's words for an empty list (`HubApi.todo`'s `empty_text`, from its `empty`); the window keeps its own copy
# (hub-ui copy.ts `EMPTY`) until phase 6
TODO_EMPTY = {"all_lossless": "Everything is lossless.", "all_hidden": "Only hidden tracks are left.",
              "nothing_here": "Nothing here."}


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


# English month abbreviations, never the locale's (the words are the engine's, the window and the command line say the
# same thing)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def short_day(d: date, today: date) -> str:
    """A day in few words: "12 Nov" in `today`'s year, "12 Nov 2025" otherwise."""
    day = f"{d.day} {MONTHS[d.month - 1]}"
    return day if d.year == today.year else f"{day} {d.year}"
