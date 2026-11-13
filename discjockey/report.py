"""Plan text for the terminal, the run report, and not_lossless.md."""
from __future__ import annotations

import json
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

from .events import Result
from .library import Paths
from . import models
from .models import SERVICE_NAMES, SOURCE_NAMES, Action, Plan
from .names import expected_stem

SECTIONS = [
    ("new_lossless", "New lossless tracks"),
    ("new_not_lossless", "New tracks that are not lossless"),
    ("fake", "Fake lossless (the Qobuz file is really lossy)"),
    ("upgrade_ready", "Better version found, waiting for you (run discjockey upgrades)"),
    ("swapped", "Swapped in the better version (cue points stay)"),
    ("added_new", "Better version added as a new file"),
    ("upgraded", "Upgraded (your cues stayed)"),
    ("upgrade_waits", "Upgrades still waiting"),
    ("converted", "Converted to AIFF (your cues stayed)"),
    ("renamed", "Given its clean name (your cues stayed)"),
    ("discarded", "Better versions you discarded"),
    ("checked", "Looked for a better version, nothing yet"),
    ("bought", "Bought files added"),
    ("replaced", "Replaced with another version you picked"),
    ("rejected", "Marked as the wrong song (searched again next run)"),
    ("hidden", "Hidden from the to-do list"),
    ("unhidden", "Back on the to-do list"),
    ("redownloaded", "Downloaded again (the file was gone)"),
    ("dropped", "No longer in any playlist (the files stay where they are)"),
    ("missing", "Not found anywhere"),
    ("queued", "Waiting for the next run"),
    ("ambiguous", "Several files could be this track, nothing done"),
    ("skipped", "Skipped playlist items"),
    ("rekordbox_check", "Check in rekordbox"),
    ("recovered", "Finished from an interrupted run"),
    ("errors", "Errors (tried again next run)"),
]
REKORDBOX_CHECK = {
    "wrong_song": "This track now plays the right song. In rekordbox: analyse it again and delete the old cues (they "
                  "belong to the wrong song).",
    "added_as_new": "This is a different edit. In rekordbox: analyse it again and set the cues again.",
}
# added_as_new when the two files were measured as the same edit (upgrades.add_new stores the measurement as `match`)
SWAPPED_CHECK = ("The lossless audio is in your file, so rekordbox keeps its cues. In rekordbox: Reload Tag, and "
                 "analyse it again so the waveform shows the full sound.")
SWAPPED_MOVED_CHECK = ("The lossless audio is in your file, which moved up out of not_lossless/. In rekordbox: Auto "
                       "Relocate finds it by its name with its cues, then Reload Tag and analyse it again.")
# the swap wrote rekordbox's text itself (plan stage B §0.6: `reload_tag: false`), so no Reload Tag
SWAPPED_WRITTEN_CHECK = ("The lossless audio is in your file, so rekordbox keeps its cues, and Discjockey updated its "
                         "names in rekordbox. In rekordbox: analyse it again so the waveform shows the full sound.")
SWAPPED_MOVED_WRITTEN_CHECK = ("The lossless audio is in your file, which moved up out of not_lossless/, and "
                               "Discjockey updated its names in rekordbox. In rekordbox: Auto Relocate finds it by its "
                               "name with its cues, then analyse it again.")
# design §8 (binding): a Same track that made a new AIFF and pointed rekordbox's track at it
REPOINTED_CHECK = ("The better audio is in a new AIFF with a clean name, and your rekordbox track plays it with its "
                   "cues, playlists and history. In rekordbox, analyse it again so the waveform shows the full sound "
                   "(lock the beatgrid first if you set it by hand).")
REPOINTED_NO_TRACK_CHECK = ("The better audio is in a new AIFF with a clean name. This file isn't in your rekordbox "
                            "collection, so there was nothing to keep there.")
# design §8 (binding): a Convert to AIFF; the sound is the same, so there is no analyse step
CONVERTED_CHECK = ("Your file is now an AIFF with a clean name and tags, and your rekordbox track plays it with its "
                   "cues, playlists and history. The sound is the same.")
CONVERTED_NO_TRACK_CHECK = ("Your file is now an AIFF with a clean name and tags. This file isn't in your rekordbox "
                            "collection, so there was nothing to keep there.")
# design §8 (binding): Give it its clean name; the audio and the tags didn't change, so there is no analyse step
RENAMED_CHECK = ("Your file has its clean name now, and your rekordbox track follows it with its cues, playlists "
                 "and history.")
RENAMED_NO_TRACK_CHECK = ("Your file has its clean name now. This file isn't in your rekordbox collection, so there "
                          "was nothing to keep there.")
# design §5.11, §8 (binding): the Reload Tag step for tracks whose text Discjockey didn't write (a batch card lists them)
RELOAD_TAG_STEP = ("In rekordbox's Collection, select the tracks listed here (⌘-click each), right-click › Reload Tag. "
                   "Don't select all: it replaces every name you changed in rekordbox on the tracks you select.")
# design §8, result 3 (until the live test settles it)
USB_STEP = "On a USB stick? The stick still plays the old file. Rebuild the stick in rekordbox before your next gig."
ALIGNED_EDIT_CHECK = ("This is the same edit, lined up with your old file to the sample. In rekordbox: relocate your "
                      "old track to the new file (right-click › Relocate); its cues fit exactly.")
SAME_EDIT_CHECK = "This is the same edit. In rekordbox: relocate the old entry to the new file, its cues fit."
SHIFTED_EDIT_CHECK = ("This is the same edit, {ms:.0f} ms apart. In rekordbox: relocate the old entry to the new "
                      "file, its cues fit to within {ms:.0f} ms.")
STATUS_TEXT = {"not_lossless": "not lossless", "fake_lossless": "fake lossless", "missing": "not found"}
PLAN_LABELS = [
    ("acquire:new", "Download (new)"),
    ("acquire:retry", "Try again (not found last time)"),
    ("acquire:redownload", "Download again (the file is gone)"),
    ("adopt_bought", "Add a bought file"),
    ("upgrade", "Look for a better version"),
]


def track_link(track_id: str) -> str | None:
    """The track's page on its own service (Spotify, Qobuz, SoundCloud, YouTube Music), or None when its key gives no
    link."""
    return models.track_link(track_id)


def service_link(track_id: str) -> str:
    """A Markdown link labelled with the track's service, plus the separator; empty when there is no link."""
    url = track_link(track_id)
    return f"[{SERVICE_NAMES[models.split_token(track_id)[0]]}]({url}) · " if url else ""


def buy_links(artist: str, title: str) -> str:
    q = quote_plus(f"{artist} {title}")
    return f"[Beatport](https://www.beatport.com/search?q={q}) · [Bandcamp](https://bandcamp.com/search?q={q})"


@dataclass
class RunLog:
    """Everything one run did, as structured results. Rendered to reports/<time>.md and saved as .json for the hub."""
    started: datetime
    results: list[Result] = field(default_factory=list)
    crashed: str | None = None  # the crash note (crash_note) when the run stopped on an unexpected error
    auto_upgrade: dict | None = None  # the Auto-upgrade phase's block (auto_upgrade.Outcome.to_dict); None: switch off
    crash_details: str = ""  # the error and its traceback, for a bug report: below the note, never in it

    def add(self, result: Result) -> None:
        self.results.append(result)

    def add_text(self, section: str, text: str) -> None:
        self.results.append(Result(section, "", "", "", note=text))

    def section(self, key: str) -> list[Result]:
        return [r for r in self.results if r.section == key]

    def is_empty(self) -> bool:
        return not self.results


OWN_FOLDER_LABEL = "your music"  # a song of the user's own is in no playlist folder (plan library stage 4)


def result_folder(a: Action, e: dict | None, where: Callable[[str], str] | None = None) -> str:
    """The folder a result is filed under in a run report: the action's playlist folder, else (an upgrade check of
    an own song, which has no playlist) the folder its file sits in, named as Sync names it. "" when that can't be
    told: the report then says "your music" (folder_label)."""
    if a.folder:
        return a.folder
    path = e.get("path") if e else None
    return (where(path) if where and path else "") or ""


def folder_label(folder: str | None) -> str:
    """The `[…]` in front of a song in reports and console lines: its playlist folder, else "your music"."""
    return folder or OWN_FOLDER_LABEL


def render_line(r: Result) -> str:
    if not (r.artist or r.title):
        return f"- {r.note}"
    text = f"- [{folder_label(r.folder)}] {r.artist} - {r.title}"
    if r.note:
        text += f" — {r.note}"
    if r.track_id and track_link(r.track_id):
        text += f" — {track_link(r.track_id)}"
    return text


def render_report(log: RunLog, finished: datetime) -> str:
    out = [f"# Discjockey run {log.started:%Y-%m-%d %H:%M:%S}", "", f"Finished at {finished:%H:%M:%S}.", ""]
    if log.crashed:
        out += [f"## {CRASHED}", "", log.crashed, ""]
    if line := auto_upgrade_line(log.auto_upgrade):
        out += [line, ""]
    for key, heading in SECTIONS:
        items = log.section(key)
        if items:
            out += [f"## {heading} ({len(items)})", "", *(render_line(r) for r in items), ""]
            if key == "upgraded" and (log.auto_upgrade or {}).get("backup"):
                out += [UPGRADE_BACKUP.format(id=log.auto_upgrade["backup"]), ""]
    if log.is_empty() and not log.crashed:
        out.append("Nothing happened in this run.")
    if log.crash_details:
        out += ["## Details for a bug report", "", "```", log.crash_details.rstrip(), "```", ""]
    return "\n".join(out) + "\n"


CRASHED = "The sync stopped unexpectedly"
# plan stage C §3 (binding)
UPGRADE_BACKUP = "Backup of your rekordbox library from before these upgrades: {id}"


CRASH_SAVED = "Everything done up to then is saved, and the next sync carries on from there."
CRASH_MESSAGE = f"{CRASHED}. {CRASH_SAVED}"  # what the window says about a crashed sync


def crash_note(at: datetime, step: str) -> str:
    """The crash note's main text: when, the step it was on, and that what was done is saved (no error type)."""
    return f"{CRASHED} at {at:%H:%M:%S} while {step}. {CRASH_SAVED}"


def write_crash(paths: Paths, log: RunLog, at: datetime, step: str, error: BaseException,
                state: dict | None = None) -> Path:
    """Files a run that stopped on an unexpected error: its report (exit code 1) with the crash note on top, the
    results so far under it, and the technical details (the error, then the traceback) at the very end. Returns
    the .md path."""
    log.crashed = crash_note(at, step)
    log.crash_details = f"{type(error).__name__}: {error}\n\n" + "".join(traceback.format_exception(error))
    return write_run(paths, log, at, 1, state)


def check_text(check: dict) -> str:
    """What to do in rekordbox for an entry's `rekordbox_check` ({reason, since}; an added_as_new also has `match`, the
    measurement of the two files, `offset_ms` and `aligned`, whether the new file was lined up with rekordbox's
    timeline of the old one; a swapped one `moved`, whether the file moved up out of not_lossless/, and `reload_tag`,
    false when Discjockey wrote rekordbox's text itself; a repointed, converted or renamed one `rekordbox`, the tracks it
    pointed at the new AIFF or name, or None when the file had none). Same edit
    (exact or shifted): the old entry can be relocated to the new file and keeps its cues, exactly when it was lined
    up. A real mismatch, no measurement or a record from before it: analyse and cue again."""
    check = check or {}
    if check.get("reason") == "swapped":
        if check.get("reload_tag") is False:  # stage B wrote rekordbox's text; older records keep Reload Tag
            return SWAPPED_MOVED_WRITTEN_CHECK if check.get("moved") else SWAPPED_WRITTEN_CHECK
        return SWAPPED_MOVED_CHECK if check.get("moved") else SWAPPED_CHECK
    if check.get("reason") == "repointed":
        return REPOINTED_CHECK if check.get("rekordbox") else REPOINTED_NO_TRACK_CHECK
    if check.get("reason") == "converted":
        return CONVERTED_CHECK if check.get("rekordbox") else CONVERTED_NO_TRACK_CHECK
    if check.get("reason") == "renamed":
        return RENAMED_CHECK if check.get("rekordbox") else RENAMED_NO_TRACK_CHECK
    if check.get("reason") == "added_as_new":
        if check.get("aligned") and check.get("match") in ("exact", "shifted"):
            return ALIGNED_EDIT_CHECK
        if check.get("match") == "exact":
            return SAME_EDIT_CHECK
        if check.get("match") == "shifted":
            return SHIFTED_EDIT_CHECK.format(ms=abs(check.get("offset_ms") or 0))
    return REKORDBOX_CHECK.get(check.get("reason"), "Check this track in rekordbox.")


def rekordbox_checks(state: dict) -> list[tuple[str, dict]]:
    """Tracks whose file changed in a way rekordbox does not notice by itself (until the user says it is done)."""
    return [(k, e) for k, e in state["tracks"].items() if e.get("rekordbox_check")]


def write_run(paths: Paths, log: RunLog, finished: datetime, exit_code: int, state: dict | None = None) -> Path:
    """Writes reports/<time>.md (to read) and reports/<time>.json (for the hub's history). Returns the .md path.
    With `state`, the tracks still to check in rekordbox are listed too."""
    if state is not None:
        log.results = [r for r in log.results if r.section != "rekordbox_check"]
        for k, e in rekordbox_checks(state):
            log.add(Result("rekordbox_check", e["folder"], e["artist"], e["title"], k,
                           check_text(e["rekordbox_check"])))
    paths.reports.mkdir(parents=True, exist_ok=True)
    stem = paths.reports / f"{log.started:%Y-%m-%d_%H%M%S}"
    md = stem.with_suffix(".md")
    md.write_text(render_report(log, finished), encoding="utf-8")
    data = {"started": log.started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"),
            "exit_code": exit_code, "results": [asdict(r) for r in log.results]}
    if log.crashed:
        data["crashed"] = log.crashed
    if log.auto_upgrade is not None:
        data["auto_upgrade"] = log.auto_upgrade
    stem.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return md


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def auto_upgrade_line(block: dict | None) -> str | None:
    """The run's one-line account of its Auto-upgrade phase (plan stage C §3; the console's summary, the report and
    the end screen). `block` is `auto_upgrade.Outcome.to_dict()`; None when the switch was off or there was nothing to
    say. Clauses: upgraded; waiting for rekordbox; waiting for the next sync (Stop, another window); refused."""
    if not block:
        return None
    results = block.get("results") or []
    n = block.get("done") or 0
    m = sum(1 for r in results if r.get("state") == "waiting" and r.get("reason") == "rekordbox_open")
    j = sum(1 for r in results if r.get("state") == "waiting" and r.get("reason") != "rekordbox_open")
    k = block.get("refused") or 0
    if not (n or m or j or k):
        return None
    if n:
        out = [f"Upgraded {_plural(n, 'track', 'tracks')}; your cues stayed."]
        if m:
            out.append(f"{m} {'waits' if m == 1 else 'wait'} for rekordbox to be closed.")
        if j:
            out.append(f"{j} {'waits' if j == 1 else 'wait'} for your next sync.")
        if k:
            out.append(f"{k} couldn't go in; To-do says why.")
        return " ".join(out)
    out = []
    if m:
        out.append(f"{_plural(m, 'upgrade waits', 'upgrades wait')} for rekordbox to be closed.")
    if j:
        out.append(f"{_plural(j, 'upgrade waits', 'upgrades wait')} for your next sync.")
    if k:
        out.append(f"{_plural(k, 'upgrade', 'upgrades')} couldn't go in; To-do says why.")
    return " ".join(out)


def upgrades_waiting(state: dict) -> int:
    return sum(1 for e in state["tracks"].values() if e.get("upgrade"))


def ready_hint(count: int) -> str:
    if count == 1:
        return "1 better version is ready: run `discjockey upgrades`."
    return f"{count} better versions are ready: run `discjockey upgrades`."


def summary(log: RunLog, path: Path, upgrades_ready: int = 0) -> str:
    out = ["", "Done."]
    for key, heading in SECTIONS:
        if log.section(key) and key != "rekordbox_check":
            out.append(f"  {heading}: {len(log.section(key))}")
    checks = len(log.section("rekordbox_check"))
    if checks:
        out.append(f"{checks} track{'s' if checks != 1 else ''} to check in rekordbox (see the report)")
    out.append(f"Full report: {path}")
    if upgrades_ready:
        out.append(ready_hint(upgrades_ready))
    return "\n".join(out)


def render_not_lossless(state: dict) -> str:
    groups: dict[str, list[tuple[str, dict]]] = {}
    for track_id, e in state["tracks"].items():
        never = e["status"] == "missing" and track_id in (state.get("never") or {})
        if e.get("in_playlists") and e["status"] in STATUS_TEXT and not never:
            groups.setdefault(e["folder"], []).append((track_id, e))
    out = [
        "# Tracks that are not lossless yet", "",
        "Made by Discjockey. To replace one with a bought copy, save the file under the name shown "
        "(as .wav or .aiff) and run Discjockey again.", "",
    ]
    if not groups:
        out.append("Every track in your playlists is lossless.")
    for folder in sorted(groups, key=str.casefold):
        out += [f"## {folder}", ""]
        for track_id, e in sorted(groups[folder], key=lambda x: (x[1]["artist"].casefold(), x[1]["title"].casefold())):
            detail = STATUS_TEXT[e["status"]]
            if e.get("source"):
                detail += f", from {SOURCE_NAMES[e['source']]}"
            if e.get("source_kbps") and e["status"] == "not_lossless":
                detail += f", {e['source_kbps']} kbps"
            if e.get("cutoff_hz"):
                detail += f", cutoff {e['cutoff_hz'] / 1000:.1f} kHz"
            hidden = " (hidden)" if e.get("hidden") else ""
            out.append(f"- **{e['artist']} - {e['title']}**{hidden} ({detail}) · {service_link(track_id)}"
                       f"{buy_links(e['artist'], e['title'])}")
            for f in e.get("free_downloads") or []:
                what = "on SoundCloud" if f.get("direct") else f"on {f.get('host')}"
                out.append(f"  - Free download from the artist {what}: [{f.get('title') or 'link'}]({f['url']})"
                           + (f" (uploaded by {f['uploader']})" if f.get("uploader") else ""))
            if e.get("upgrade"):
                text = (e["upgrade"].get("alignment") or {}).get("text")
                out.append("  - Better version ready: run `discjockey upgrades`" + (f" ({text})" if text else ""))
            out.append(f"  - Bought copy goes to: `Library/{folder}/{expected_stem(e['artist'], e['title'])}.wav` "
                       "(or `.aiff`)")
        out.append("")
    return "\n".join(out) + "\n"


def write_not_lossless(paths: Paths, state: dict) -> None:
    paths.not_lossless_md.parent.mkdir(parents=True, exist_ok=True)
    paths.not_lossless_md.write_text(render_not_lossless(state), encoding="utf-8")


def render_plan(plan: Plan, full: bool, where: Callable[[str], str] | None = None) -> str:
    """The console's plan (the dry run's list, the lines before a run). Each song under the folder its run report
    files it under (`result_folder`): an own song's by the folder its file sits in (`where`, as Sync names it)."""
    groups: dict[str, list] = {}
    for a in plan.actions:
        groups.setdefault(f"acquire:{a.reason}" if a.kind == "acquire" else a.kind, []).append(a)
    out: list[str] = []
    for key, label in PLAN_LABELS:
        items = groups.get(key, [])
        if not items:
            continue
        out.append(f"{label}: {len(items)}")
        shown = items if full else items[:20]
        for a in shown:
            folder = result_folder(a, plan.state["tracks"].get(a.track_id), where)
            out.append(f"    [{folder_label(folder)}] {a.track.first_artist} - {a.track.title}")
        if len(shown) < len(items):
            out.append(f"    ... and {len(items) - len(shown)} more")
    if plan.ambiguous:
        out.append(f"Several matching files, skipped: {len(plan.ambiguous)}")
        for _key, t, folder, files in plan.ambiguous:
            out.append(f"    [{folder}] {t.first_artist} - {t.title}: {', '.join(files)}")
    if plan.dropped:
        out.append(f"No longer in any playlist (files stay): {len(plan.dropped)}")
        for key in plan.dropped[: None if full else 20]:
            e = plan.state["tracks"][key]
            out.append(f"    [{e['folder']}] {e['artist']} - {e['title']}")
    for note in plan.notes:
        out.append(f"Note: {note}")
    if plan.never:
        out.append(f"Never download (your choice in the hub): {len(plan.never)}")
    if not out:
        out.append("Library is up to date.")
    return "\n".join(out)
