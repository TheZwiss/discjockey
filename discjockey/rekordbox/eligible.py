"""Pure: what Same track, Convert to AIFF and Give it its clean name would do for one track, and why not (design
rekordbox-repoint §2.2, §3.5, §5.11; plan stage A §2). No I/O: callers read the facts (`audio.file_facts`, the
rekordbox answer, whether the file is there) and hand them in; the commands, the later bridge method and the batches
all ask these same functions, so a button's count and a command's answer can't differ.

Each action answers `Eligible()` or `Skip(reason)`; the reason keys are `REASONS` (the words are the preview's and
the window's). `entry` is the song's snapshot entry (`library.load_state`'s `tracks[key]`), `facts` the file's
`audio.FileFacts`, `rb` rekordbox's `master.Status`, `timing` what `rekordbox.timeline_offset` found for the file
(None: not measured, which only matters to a file that isn't an AIFF), `present` whether the file is there:
`"here"`, `"away"` (its drive isn't connected) or `"missing"`.

What rekordbox does not stop in stage A, and does in stage B: rekordbox being open (a run-time refusal, design §5.6),
an unclean library, a changed track, too little space. Those join `REASONS` then.

Tags: `expected_tags` is what the new file's text would say (title and artists from the song record, album from the
record when it has one, the rest from the old file; the comment is the quality line), `tags_clean` whether a file
already says that, `text_plan` which of rekordbox's six text columns a repoint may overwrite and which hold the user's
own edit (design §5.11).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from .. import quality
from ..audio import TEXT_FIELDS, FileFacts
from ..models import SOURCE_NAMES
from ..names import fold
from .master import Entry, Status
from .offset import TimelineOffset

REASONS = ("no_upgrade", "needs_choice", "file_missing", "away", "rekordbox_unreadable", "timing", "not_analysed",
           "cloud", "downloaded", "clean_aiff", "named_already", "needs_convert", "no_name", "not_in_library",
           "auto_refused")  # auto_refused is reserved for stage C
ACTIONS = ("same_track", "convert", "rename")
AIFF_EXTS = (".aiff", ".aif")
OWN = "manual"  # the `source` of a file that wasn't downloaded: a bought file or one the import found

Present = Literal["here", "away", "missing"]


@dataclass(frozen=True)
class Eligible:
    """The action can run."""


@dataclass(frozen=True)
class Skip:
    """The action can't run now: `reason` is one of REASONS."""
    reason: str


Verdict = Eligible | Skip


def reason_of(verdict: Verdict) -> str | None:
    """The `eligible` value of the commands' JSON: None means eligible."""
    return verdict.reason if isinstance(verdict, Skip) else None


def _norm(text: str | None) -> str:
    return unicodedata.normalize("NFC", text or "").strip()


# --- the new file's text ---

def _artists(entry: dict) -> str:
    return ", ".join(entry.get("artists") or ()) or entry.get("artist") or ""


def expected_tags(entry: dict, old_tags: dict[str, str]) -> dict[str, str]:
    """The text the new file would carry, one value per `TEXT_FIELDS`: title and artists (joined by ", ") from the song
    record; album and ISRC from the record when it has them, else the old file's; label from the old file (the record
    has none); the comment is the quality line of the old file's format (a file of the user's own reads "Your own file (MP3)
    · …"), else the old comment when the record has no source."""
    old = {f: old_tags.get(f, "") for f in TEXT_FIELDS}
    comment = old["comment"]
    if entry.get("source") in SOURCE_NAMES:
        comment = quality.quality_line(entry["source"], entry.get("source_format") or "?",
                                       entry.get("status") or "lossless", entry.get("cutoff_hz"),
                                       entry.get("source_kbps"), own=entry.get("placed_by") == "import")
    return {"title": entry.get("title") or "", "artist": _artists(entry),
            "album": entry.get("album") or old["album"], "label": old["label"],
            "isrc": entry.get("isrc") or old["isrc"], "comment": comment}


def tags_clean(facts: FileFacts, entry: dict) -> bool:
    """Whether the file already says what `write_tags` would write from the song record: title, artists and album
    equal (NFC, trimmed), and a cover when the record has one (design §2.2)."""
    expected = expected_tags(entry, facts.tags)
    same = all(_norm(facts.tags.get(f)) == _norm(expected[f]) for f in ("title", "artist", "album"))
    return same and (facts.has_cover or not entry.get("image_url"))


def text_plan(row: Entry, old_tags: dict[str, str], clean: dict[str, str]) -> dict[str, str]:
    """Per text column of rekordbox's track `row`: "write" where the repoint may put the clean value there, "kept"
    where the user's own edit stays. A field is written when rekordbox's value still equals the old file's tag, or
    already equals the clean value (nothing to lose); an empty field and a missing tag are equal."""
    plan = {}
    for field in TEXT_FIELDS:
        shown = _norm(getattr(row, field))
        safe = shown in (_norm(old_tags.get(field)), _norm(clean.get(field)))
        plan[field] = "write" if safe else "kept"
    return plan


def fields_kept(row: Entry, old_tags: dict[str, str], clean: dict[str, str]) -> list[str]:
    return [f for f, what in text_plan(row, old_tags, clean).items() if what == "kept"]


# --- the three actions ---

def is_clean_aiff(facts: FileFacts, entry: dict) -> bool:
    """An AIFF in the library format (16-bit, 44.1 kHz) whose tags are the download's."""
    return (facts.ext in AIFF_EXTS and facts.codec.startswith("pcm_s16") and facts.bits == 16
            and facts.sample_rate == 44100 and tags_clean(facts, entry))


def _is_aiff_16_44(facts: FileFacts) -> bool:
    return facts.ext in AIFF_EXTS and facts.codec.startswith("pcm_s16") and facts.bits == 16 and facts.sample_rate == 44100


def _where(present: Present) -> Skip | None:
    return None if present == "here" else Skip("away" if present == "away" else "file_missing")


def _rekordbox_blocks(rb: Status, timing: TimelineOffset | None, *, audio_changes: bool = True) -> Skip | None:
    """Why rekordbox can't follow a new file for this track, else None: its library can't be read (a file that
    could be in it can't be repointed), a track in Cloud Library Sync, or (`audio_changes`) no exact timeline offset.
    A rename keeps the audio, so the timeline doesn't matter to it (design §7.1)."""
    if rb.state == "unreadable" or (timing is not None and timing.why == "unreadable"):
        return Skip("rekordbox_unreadable")
    if timing is None:
        return None
    if any(t.entry.cloud for t in timing.entries):
        return Skip("cloud")
    if audio_changes and timing.why in ("not_analysed", "timing"):
        return Skip(timing.why)
    return None


def same_track(entry: dict, facts: FileFacts | None, rb: Status, timing: TimelineOffset | None, *,
               present: Present = "here") -> Verdict:
    """A parked upgrade of the same edit goes in place of the current file. An AIFF takes the audio in place (rekordbox
    needs nothing); any other format becomes a new AIFF that rekordbox's track is pointed at, which needs rekordbox
    readable, no cloud track and a known offset. The alignment is the one the upgrade check stored; the run measures
    it again."""
    if not entry.get("upgrade"):
        return Skip("no_upgrade")
    if (gone := _where(present)) is not None:
        return gone
    if (entry["upgrade"].get("alignment") or {}).get("result") not in ("exact", "shifted"):
        return Skip("needs_choice")
    if facts is not None and facts.ext in AIFF_EXTS:
        return Eligible()
    return _rekordbox_blocks(rb, timing) or Eligible()


def convert(entry: dict, facts: FileFacts | None, rb: Status, timing: TimelineOffset | None, *,
            present: Present = "here") -> Verdict:
    """The user's own file becomes the download's format: a 16-bit/44.1 kHz AIFF with the clean tags, rekordbox's track
    pointed at it. Not for a file Discjockey downloaded, a file that already is that, or one rekordbox can't follow."""
    if (gone := _where(present)) is not None:
        return gone
    if entry.get("source") != OWN:
        return Skip("downloaded")
    if not (entry.get("artist") or "").strip() or not (entry.get("title") or "").strip():
        return Skip("no_name")
    if facts is not None and is_clean_aiff(facts, entry):
        return Skip("clean_aiff")
    return _rekordbox_blocks(rb, timing) or Eligible()


def rename(entry: dict, facts: FileFacts | None, rb: Status, timing: TimelineOffset | None, *,
           present: Present = "here", clean_path: str | None = None) -> Verdict:
    """An own clean AIFF gets its clean name. `clean_path` is the path that name would be (the NameReserver's answer
    with the file's own name free); the file is named already when it is that path."""
    if (gone := _where(present)) is not None:
        return gone
    if entry.get("source") != OWN:
        return Skip("downloaded")
    if not (entry.get("artist") or "").strip() or not (entry.get("title") or "").strip():
        return Skip("no_name")
    if facts is None or not is_clean_aiff(facts, entry):
        return Skip("needs_convert")
    if clean_path is not None and fold(clean_path) == fold(entry.get("path") or ""):
        return Skip("named_already")
    return _rekordbox_blocks(rb, timing, audio_changes=False) or Eligible()
