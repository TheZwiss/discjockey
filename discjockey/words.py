"""The words the engine owns for the command line (issue 39, design §8.3): the steps only a person can do after a
change that rekordbox does not notice by itself. The window still builds its own numbered steps from the same facts
(`decisionModel.ts`); phase 6 splits these into numbered steps and takes that copy away. A later group adds the words
of the other answers here.

The module also holds the window's banner words for another process's job (`JOB_TITLES`, `job_title`, `holder_text`,
`holder_where`, `UNNAMED_HOLDER`, `HOLDER_PLACES`, `HOLDER_WHERE`): `Jobs._holder_of` makes them, and they reach the
window as `ConsoleBusy.text` / `ConsoleBusy.where`, `JobStatus.console` and `Busy.data.holder`.

`person_steps` turns one open rekordbox check into the steps of `HubApi.todo`'s `check.person_steps`: the step's `id`
and `then` come from `outcomes.STEPS`, its `say` is the engine's own sentence for the check (`report.check_text`, with
the USB step where the check has one: `report.usb_step`). The track's name is its key: `check done <key>` is the next
command."""
from __future__ import annotations

from collections.abc import Mapping
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
    "library": "Your library: list it, its collections, what is in Superseded/, read it again, read file facts.",
    "missing": "Songs whose file is missing: list them, download again or remove from your library.",
    "rekordbox": "rekordbox's library: its state, whether it matches your files, what a change would do, its backups.",
    "report": "The reports of past syncs: list them, show one.",
    "settings": "What Settings holds, and changing it.",
    "status": "What the Dashboard shows, the running jobs, and whether you're ready for a gig.",
    "sync": "The sync: read your playlists, see the plan, run it.",
    "todo": "Your to-do list.",
    "track": "One song: find it, show it, its spectrum, undo its last step.",
    "upgrade": "Better versions waiting: list, put in, throw away.",
    "job": "Long runs: list, show, follow, wait for, stop.",
    "tidy": "Files out of playlist order: see what a tidy-up would move.",
    "limits": "The daily download limits: what is used, what another limit would do.",
    "playlist": "Your playlists: list them, check a link before you add it.",
    "login": "The download logins: their state, the browsers that hold one.",
    "tools": "The programs Discjockey needs: are they there.",
    "setup": "Setup: what it still needs, whether a folder can be your music folder.",
    "app": "This app: open its window, its version and whether a newer one is out.",
    "open": "Show a song, a folder or a report in the Finder, or open a web page.",
    "history": "What changed, newest first, and how to undo it.",
    "doctor": "Everything that is wrong, and what to do about it.",
}

NO_PLAYLIST = "No playlist called “{name}”."
NO_SONG = "Your library has no song {key}. `track find <words>` finds a song's id."
NO_REPORT_YET = "There is no run report yet."
NO_BUY_LIST = "There is no buy list yet: Discjockey writes it when a sync finds songs it can only get lossy."
NO_PLACE = "unlisted is no single folder: say all, playlist:<name>, folder:<path> or a path."
NO_REPORT = "There is no report {stamp}. `report show last` shows the newest; a sync prints the id of its report."
NO_FOLDER = "No folder at {path}."
NOT_WATCHED = "{path} is not one of the watched folders."
LIBRARY_NOT_REMOVABLE = "{path} is your Library: it is always watched and cannot be removed."
BAD_FOLDER = "A folder is its path, or folder:<path>."
BAD_COLLECTION = "A collection is all, unlisted, playlist:<name> or folder:<path>."
UPDATE_NO_ANSWER_DEV = "No answer: this is a developer's version."  # `app info --check` that asked nobody
UPDATE_NO_ANSWER_OFFLINE = "No answer: GitHub could not be reached."  # `app info --check` that asked and got nothing
BAD_SINCE = ("--since takes today, yesterday, a number of days or hours (3d, 12h) or a date or time (2026-11-20, "
             "2026-11-20T18:00), not {text}.")

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

# `sync run` (`HubApi.start_sync`): what it refuses before a job starts.
SYNC_IDS_NEED_PLAN = "Action ids belong to a plan: say --plan with the plan_id of the sync plan that showed them."
SYNC_IDS_OR_HOW_MANY = "Say the actions or how many, not both."
SYNC_NEEDS_READ = "Your playlists have not been read yet, so there is no plan to run."
BAD_HOW_MANY = "--how-many takes 5, 10, 25, 50, fits, all or a number."
SYNC_READING = "A sync is running; it reads your playlists itself."


# What the openers say (`Opened.text`: `show_in_finder`, `reveal`, `open_report`, `open_licenses`, `open_external`,
# `open_privacy_settings`; the command line's `open ...`).
OPENED = "Opened {target}."
NOT_OPENED = "Would open {target}; nothing was opened."  # with `--print`


# `history` (design §5.3, §7.4): the text of each entry, and for each one the command that undoes it or the words that say
# why nothing does. `HISTORY_RUN` is by the run's kind; an AIFF batch says what it did (`HISTORY_AIFF`, by the batch's
# `what`), or "Upgraded during your sync" when the sync's last phase made it; a move batch says its title and what moved.
BATCH_MADE_AIFF = "Made AIFF"  # the sub of the To-do item of a Convert batch's checks (plan stage D §3), and a history entry's
AUTO_BATCH_DETAIL = "Upgraded during your sync"  # the sub of the To-do item of an Auto-upgrade batch's checks, and a history entry's
BATCH_CLEAN_NAME = "Clean name"  # the sub of a batch that only gave clean names, in the To-do list and in `history`
BATCH_PLACED = "Better versions put in during your sync"  # ... of a batch of placements only (issue 43), in both
HISTORY_RUN = {report.SYNC: "Sync: {lossless} lossless, {lossy} lossy, {moved} moved, {problems} to look at",
               report.AUTO_UPGRADE_ONLY: "Auto-upgrade alone: {line}"}  # by the report's kind
HISTORY_RUN_NOTHING = "nothing to do"
HISTORY_AIFF = {"upgrade": "Better versions put in", "convert": BATCH_MADE_AIFF,
                "mixed": "Better versions put in and made AIFF"}
HISTORY_AIFF_DONE = "{what} · {done} of {total} done"
# a logged step, by the operation's name in operations.jsonl; a name that is not here says itself
OPERATION_WORDS = {
    "upgrade_same_track": "better version put in",
    "upgrade_add_new": "better version added as a new track",
    "upgrade_place": "parked version put in for its missing file",
    "upgrade_discard": "better version thrown away",
    "aiff_convert": "made AIFF",
    "aiff_rename": "given its clean name",
    "undo_upgrade": "upgrade undone",
    "undo_convert": "AIFF undone",
    "undo_rename": "clean name undone",
    "rekordbox_checked": "checked in rekordbox",
    "move_to_superseded": "other files moved to Superseded/",
    "never download": "set to never download",
    "download allowed": "allowed to download again",
    "download again": "to be downloaded again (its file was missing)",
    "removed from library": "removed from your library",
    "hide": "hidden",
    "unhide": "shown again",
    "add_bought_file": "bought file added",
    "use_candidate": "another version downloaded",
    "use_link": "downloaded from a link",
    "reject_current": "its version turned down",
}
UNDO_NOT_YET = "Undoing this comes in a later version ({command})."
RUN_CANT = "A sync's downloads stay: Discjockey never deletes music."
RUN_CANT_AUTO = "Its upgrades are listed as a batch: undo that one."  # an Auto-upgrade-only run
STILL_RUNNING = "Still running."
WAS_UNDO = "This was an undo."
UNDONE = "Undone already."
UNDONE_BY = "Undone by {id}."
NOTHING_DONE = "Nothing was changed, so there is nothing to undo."
LATER_STEP = "A later step of this song comes first: undo that one."
NOTHING_LEFT = "Nothing left to undo: those files moved again since."
CANT_UNDO_NOW = "This step can't be undone any more: the files changed since."
SONG_GONE = "This song is no longer in your library."
DISCARD_CANT = "Thrown-away versions are not offered again."
CHECKED_CANT = "Marked as checked in rekordbox: nothing to undo."
SUPERSEDED_CANT = "The other files are in Superseded/; move one back in the Finder to use it again."
DOWNLOAD_CANT = "A download is not undone: Discjockey never deletes music."
REMOVED_CANT = "A removed song comes back when its file is added again."
NEW_VERSION_CANT = "A new version stays: Discjockey never deletes music."
UNKNOWN_CANT = "Discjockey can't undo this step."


def plural(n: int, one: str, many: str) -> str:
    """`one` when `n` is 1, else `many` with its `{n}` filled: the one helper for the count texts ("1 file moved", "3 files
    moved")."""
    return one if n == 1 else many.format(n=n)


def before_start_line(n: int) -> str:
    """Plan stage C §3's Sync before-start Hint: said before a sync starts (the Sync page). The
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

# The Sync scope's weekly kinds (`sync scope show|on|off`; the Sync page's two weekly switches)
SCOPE_KIND_LABELS = {"retry": "Not found last time", "weekly": "Weekly checks"}

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


# `rekordbox match` (does rekordbox match my files?) and `library superseded` (what sits in Superseded/?). A rekordbox
# track needs a look when its file is missing, sits in Superseded/ or is in your music folder but no song's file;
# a track on a drive that is not connected, and a file of your own elsewhere, are not problems.
MATCH_KINDS = {"missing": "File missing", "superseded": "Points at Superseded/",
               "away": "On a drive that isn't connected", "not_in_library": "In your library's folders but no song's file",
               "not_in_rekordbox": "Not in rekordbox"}
MATCH_PROBLEMS = ("1 rekordbox track needs a look", "{n} rekordbox tracks need a look")
MATCH_LACKING = ("1 of your files is not in rekordbox", "{n} of your files are not in rekordbox")
MATCH_TEXT = "{problems}, {lacking}."
MATCH_ALL_GOOD = "rekordbox and your library match."
MATCH_NO_REKORDBOX = "There is no rekordbox library on this Mac."
SUPERSEDED_FILES = ("1 file", "{n} files")
SUPERSEDED_HELD = ("still uses 1 of them", "still uses {n} of them")
SUPERSEDED_TEXT = "{files} in Superseded/, {size}; rekordbox {held}."
SUPERSEDED_BLIND = "{files} in Superseded/, {size}."  # rekordbox can't be read now: no word of what it uses
SUPERSEDED_NONE_HELD = "uses none of them"
NO_SUPERSEDED = "Superseded/ is empty."
DELETE_SUPERSEDED = "Discjockey never deletes music. You can delete these files in the Finder."


def match_text(problems: int, lacking: int) -> str:
    """The one sentence of `rekordbox match`: how many rekordbox tracks need a look and how many of your files it lacks,
    or that they match."""
    if not problems and not lacking:
        return MATCH_ALL_GOOD
    return MATCH_TEXT.format(problems=plural(problems, *MATCH_PROBLEMS), lacking=plural(lacking, *MATCH_LACKING))


def superseded_text(files: int, size: int, held: int | None) -> str:
    """The one sentence of `library superseded`: how many files, how big, and how many of them rekordbox still uses
    (`held` None: rekordbox can't be read now)."""
    count = plural(files, *SUPERSEDED_FILES)
    if held is None:
        return SUPERSEDED_BLIND.format(files=count, size=convert.size_text(size))
    return SUPERSEDED_TEXT.format(files=count, size=convert.size_text(size),
                                  held=plural(held, *SUPERSEDED_HELD) if held else SUPERSEDED_NONE_HELD)


# The music folder as the window's gate and `doctor` say it (`HubApi._paths` raises them as `no_library`)
NOT_CHOSEN = "Choose your music folder first: it is the first step of Setup."
MISSING = "Your music folder isn't there: {path}. Connect the drive it is on, or choose another folder."

# `doctor`: every check that found something says it in one sentence (a count takes its one-form through `plural`);
# what to do next is a command (`next`) or a step only the person can do (`outcomes.STEPS`)
DOCTOR_PROBLEMS = ("1 problem", "{n} problems")
DOCTOR_NOTES = ("1 note", "{n} notes")
DOCTOR_TEXT = "{problems}, {notes}."
DOCTOR_ALL_GOOD = "Nothing wrong found."
DOCTOR_TOOLS = "Programs Discjockey needs are missing: {tools}."
DOCTOR_LOGIN = "{service}: its last login check failed."
DOCTOR_ACCESS = "Discjockey can't open {folder}."
DOCTOR_FOREIGN_LOCK = "Something outside Discjockey's job list holds your library: {text}."
DOCTOR_LOST = ("1 job stopped without finishing this week.", "{n} jobs stopped without finishing this week.")
DOCTOR_PENDING = "Some file steps were cut off; the next change finishes them first."
DOCTOR_AWAY = ("1 watched folder is on a drive that isn't connected.",
               "{n} watched folders are on a drive that isn't connected.")
DOCTOR_GONE = ("1 watched folder is not there.", "{n} watched folders are not there.")  # on no external drive: moved or deleted
DOCTOR_PAUSED = "Paused today to protect your account: {services}."
# the library's own checks (a count takes its one-form through `plural`; Superseded/ reuses `SUPERSEDED_FILES`)
DOCTOR_OUT_OF_PLACE = ("1 file is not where the playlist order puts it.",
                       "{n} files are not where the playlist order puts them.")
DOCTOR_SUPERSEDED = "{files} in Superseded/, {size}."
DOCTOR_RB_FILES = ("1 rekordbox track points at a file that is missing or in Superseded/.",
                   "{n} rekordbox tracks point at files that are missing or in Superseded/.")
DOCTOR_STOPPED = ("1 batch stopped before its end.", "{n} batches stopped before their end.")
DOCTOR_CHECKS = ("1 track waits for a check in rekordbox.", "{n} tracks wait for a check in rekordbox.")
DOCTOR_CDJ = ("1 file won't play well on CDJs.", "{n} files won't play well on CDJs.")
DOCTOR_MISSING_FILES = ("1 song's file is missing.", "{n} songs' files are missing.")
DOCTOR_TO_LOAD = ("1 playlist song has no file yet.", "{n} playlist songs have no file yet.")
DOCTOR_UPGRADES = ("1 better version waits for you.", "{n} better versions wait for you.")
# the records (library.db) could not be read: the failure's own words, then that the checks reading them did not run
DOCTOR_RECORDS_SKIPPED = "The checks that read your library's records were not run."
# rekordbox is there but its tracks could not be compared with your files (`why`: the words of the read that failed)
DOCTOR_RB_NOT_COMPARED = "rekordbox's tracks could not be compared with your files: {why}."
# what each `next` of a problem is for
DOCTOR_WHY_SETUP = "what Setup still needs"
DOCTOR_WHY_REKORDBOX = "what rekordbox's library says"
DOCTOR_WHY_BACKUPS = "the backups Discjockey made of it"
DOCTOR_WHY_LOGINS = "each login's state"
DOCTOR_WHY_JOBS = "every job Discjockey knows of"
DOCTOR_WHY_LOST = "what it did before it stopped"
DOCTOR_WHY_SCAN = "finishes them, then scans"
DOCTOR_WHY_LIMITS = "today's downloads and why they paused"
DOCTOR_WHY_TIDY = "which files a tidy-up would move"
DOCTOR_WHY_SUPERSEDED = "the files and what rekordbox still uses"
DOCTOR_WHY_MATCH = "which tracks, and their files"
DOCTOR_WHY_RESUME = "goes on where it stopped"
DOCTOR_WHY_CHECKS = "the checks and what to do in rekordbox"
DOCTOR_WHY_CDJ = "the files and why"
DOCTOR_WHY_MISSING = "the songs and what can be done"
DOCTOR_WHY_SYNC_PLAN = "what the next sync downloads"
DOCTOR_WHY_UPGRADES = "the versions waiting"
DOCTOR_WHY_RECORDS = "where Discjockey keeps its records"
DOCTOR_WHY_NOT_COMPARED = "whether rekordbox can be read now"
# what each check of `doctor` looks at (keyed like `hub/doctor.py`'s `CHECKS`)
DOCTOR_LABELS = {
    "music_folder": "Music folder", "tools": "Programs", "logins": "Logins", "folder_access": "Folder access",
    "rekordbox": "rekordbox", "stale_lock": "Library lock", "lost_jobs": "Jobs", "records": "Records",
    "pending_steps": "Cut-off steps", "drives_away": "Drives", "downloads_paused": "Download limits",
    "out_of_place": "Files out of place", "superseded": "Superseded/", "rekordbox_files": "rekordbox tracks",
    "stopped_batches": "Stopped batches", "open_checks": "rekordbox checks", "cdj": "CDJ problems",
    "songs_without_file": "Songs without a file", "upgrades_waiting": "Better versions"}
# `library superseded`: why a file's `next` is offered
SUPERSEDED_WHY_OPEN = "show them in the Finder"
SUPERSEDED_WHY_MATCH = "which rekordbox tracks still use them"
# `status --ready`: the verdict in one sentence, beside the problems a gig depends on
READY_YES = "Ready for a gig: nothing to look at."
READY_NOT = ("1 thing to look at before a gig.", "{n} things to look at before a gig.")

# the apps a command can run in, by the bundle id macOS gives them and by `TERM_PROGRAM`: the app a person grants
# access to a folder (macOS charges a command to the app it started from, not to Discjockey)
APP_BY_BUNDLE = {"com.apple.Terminal": "Terminal", "com.googlecode.iterm2": "iTerm",
                 "com.microsoft.VSCode": "Visual Studio Code", "dev.warp.Warp-Stable": "Warp"}
APP_BY_TERM = {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm", "vscode": "Visual Studio Code",
               "WarpTerminal": "Warp"}
UNKNOWN_APP = "the app you run this command in"


def running_app(environ: Mapping[str, str]) -> str:
    """The app this command runs in, named as System Settings › Privacy & Security › Files and Folders names it: the
    bundle id first, else `TERM_PROGRAM`, else `UNKNOWN_APP`."""
    return (APP_BY_BUNDLE.get(environ.get("__CFBundleIdentifier", "")) or APP_BY_TERM.get(environ.get("TERM_PROGRAM", ""))
            or UNKNOWN_APP)


def doctor_superseded(files: int, size: int) -> str:
    """`doctor`'s note on Superseded/: how many files it holds and how big they are together."""
    return DOCTOR_SUPERSEDED.format(files=plural(files, *SUPERSEDED_FILES), size=convert.size_text(size))


def ready_text(n: int) -> str:
    """The sentence of `status --ready`: whether the library is ready for a gig, or how many things to look at first."""
    return plural(n, *READY_NOT) if n else READY_YES


def doctor_text(problems: int, notes: int) -> str:
    """The one sentence of `doctor`: how many problems and notes, or that there is nothing wrong."""
    if not problems and not notes:
        return DOCTOR_ALL_GOOD
    return DOCTOR_TEXT.format(problems=plural(problems, *DOCTOR_PROBLEMS), notes=plural(notes, *DOCTOR_NOTES))


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


def job_line(fields: dict) -> str | None:
    """The one line a running job's progress is said in (`state.json`'s `progress.line`, what the window's foot shows):
    "3 of 12" when the total is known, with " · <item>" when an item is in work; else the last message; else None. A
    data word (design §8.3): it counts and names, it explains nothing."""
    total = fields.get("total")
    if total is not None:
        line = f"{fields.get('done') or 0} of {total}"
        return f"{line} · {fields['item']}" if fields.get("item") else line
    return fields.get("message") or None


# A job kind as the window names it, sentence case (the banner "Sync running in the Terminal · 4 of 60"); a kind not
# listed says its own name (`job_title`)
JOB_TITLES = {
    "sync": "Sync", "refresh": "Playlists read", "tidy": "Tidy-up", "scan": "Library scan", "import": "Import",
    "aiff_batch": "AIFF conversion", "batch_resume": "AIFF batch", "upgrade_batch": "Upgrade",
    "auto_upgrade": "Auto-upgrade", "missing_files": "Missing files", "undo_moves": "Undo of a tidy-up",
    "undo_upgrade": "Undo of an upgrade", "use_candidate": "Download of a version", "use_link": "Download from a link",
    "supersede": "Same-song choice", "update_tools": "Tools update", "rollback_tools": "Tools rollback",
}
# what the banner says of a holder nobody can name: an older Discjockey or the legacy console, which may run a sync, a
# setup or an update
UNNAMED_HOLDER = "A Discjockey command is running in the Terminal"
HOLDER_PLACES = {"terminal": "the Terminal", "window": "another window"}
# where a holder runs as the Sync page's live view names it ("In the Terminal"), carried as `ConsoleBusy.where`
HOLDER_WHERE = {via: f"In {place}" for via, place in HOLDER_PLACES.items()}


def job_title(kind: str) -> str:
    """The job kind as the window names it: its entry of `JOB_TITLES`, else its words with `_` as a space and a capital
    first letter ("auto_upgrade_run" says "Auto upgrade run")."""
    return JOB_TITLES.get(kind) or kind.replace("_", " ").capitalize()


def holder_where(via: str | None) -> str:
    """Where a holder runs, for the Sync page's live view ("In the Terminal", "In another window"): the same places as
    `holder_text`, and a `via` the registry does not say counts as the Terminal too."""
    return HOLDER_WHERE.get(via or "terminal", HOLDER_WHERE["terminal"])


def holder_text(kind: str | None, via: str | None, line: str | None) -> str:
    """What the window says while another process's job holds the library (design §8.3, a data word next to its facts):
    "<job> running in the Terminal" (`via` terminal) or "... in another window" (`via` window), with " · <line>" when the
    job's progress is known; for a holder with no registry entry (`kind` None) `UNNAMED_HOLDER`. A `via` the registry
    does not say counts as the Terminal (the registry only knows `terminal` and `window`)."""
    if not kind:
        return UNNAMED_HOLDER
    place = HOLDER_PLACES.get(via or "terminal", HOLDER_PLACES["terminal"])
    text = f"{job_title(kind)} running in {place}"
    return f"{text} · {line}" if line else text
