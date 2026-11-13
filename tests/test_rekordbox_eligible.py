"""discjockey/rekordbox/eligible.py: every row of the eligibility table (design rekordbox-repoint §2.2) both ways, the
tag rules (`expected_tags`, `tags_clean`) and `text_plan`. Pure: no file is read, nothing is decoded."""
from __future__ import annotations

import pytest

from discjockey.audio import TEXT_FIELDS, FileFacts
from discjockey.rekordbox import Entry, Status, TimelineOffset
from discjockey.rekordbox.eligible import (
    ACTIONS, REASONS, Eligible, Skip, aiff_action, convert, expected_tags, fields_kept, is_lossless_codec, reason_of,
    rename, same_track, same_track_quick, tags_clean, text_plan,
)
from discjockey.rekordbox.offset import EntryTiming
from discjockey.rekordbox.preview import REASON_WORDS

READY = Status("ready", False, "7.0.0", "/rb/master.db", None, "6000", "1")
NONE = Status("none", False, None, None, None, None, None)
UNREADABLE = Status("unreadable", False, None, "/rb/master.db", "key", None, None)
TAGS = {"title": "Song", "artist": "Artist", "album": "", "label": "", "isrc": "", "comment": ""}
PATH = "Library/Mine/old name.mp3"


def entry(**kw):
    e = {"artist": "Artist", "title": "Song", "path": PATH, "source": "manual", "source_format": "mp3",
         "status": "lossless", "cutoff_hz": None, "source_kbps": None, "upgrade": None, "album": None, "isrc": None,
         "image_url": None, "artists": None}
    e.update(kw)
    return e


def facts(ext=".mp3", codec="mp3", rate=44100, bits=None, tags=None, cover=False):
    return FileFacts(ext, codec, rate, bits, {**TAGS, **(tags or {})}, cover)


def aiff(**kw):
    return facts(".aiff", "pcm_s16be", 44100, 16, **kw)


def row(cloud=False, **kw):
    base = dict(id="1", folder_path="/x", file_name="x", file_type=1, analysis_path=None, title="", artist="",
                album="", label="", isrc="", comment="", cloud=cloud, created_at=None, artist_id=None, album_id=None,
                label_id=None, org_folder_path="", local_folder_path=None, file_size=None, uuid=None)
    return Entry(**{**base, **kw})


def timing(why="measured", samples=0, cloud=False, rb=READY):
    return TimelineOffset(samples, why, rb, [EntryTiming(row(cloud=cloud), 1, True, True, None, None, None)])


def parked(result="exact"):
    return {"file": "Upgrades ready/x.aiff", "source": "qobuz", "source_id": "q1", "source_format": "flac",
            "alignment": None if result is None else {"result": result}}


def why(verdict):
    return reason_of(verdict)


# --- the reasons ---

def test_every_reason_has_its_words_and_the_actions_are_three():
    assert set(REASON_WORDS) == set(REASONS) and len(set(REASONS)) == len(REASONS)
    assert ACTIONS == ("same_track", "convert", "rename")
    assert reason_of(Eligible()) is None and reason_of(Skip("cloud")) == "cloud"
    assert {"unclean", "changed", "space", "rekordbox_open", "rename_blocked"} <= set(REASONS)  # stage B: a run finds them
    assert "not_reached" in REASONS                       # stage C: an Auto-upgrade batch that ended before this item
    assert "upgrade_waits" in REASONS                     # stage D: a parked upgrade wins over Convert and Rename


# --- Same track ---

def test_same_track_needs_a_parked_upgrade_that_is_the_same_edit():
    assert why(same_track(entry(), facts(), READY, None)) == "no_upgrade"
    for result in ("different", "unknown", None):
        assert why(same_track(entry(upgrade=parked(result)), aiff(), READY, None)) == "needs_choice", result
    for result in ("exact", "shifted"):
        assert why(same_track(entry(upgrade=parked(result)), aiff(), READY, None)) is None, result


def test_same_track_needs_the_file_there():
    e = entry(upgrade=parked())
    assert why(same_track(e, aiff(), READY, None, present="away")) == "away"
    assert why(same_track(e, aiff(), READY, None, present="missing")) == "file_missing"
    assert why(same_track(entry(), None, READY, None, present="missing")) == "no_upgrade"  # nothing waits: say that


def test_an_aiff_swaps_in_place_whatever_rekordbox_says():
    e = entry(upgrade=parked(), path="Library/Mine/x.aiff")
    for rb, t in ((UNREADABLE, None), (READY, timing("not_analysed", None)), (READY, timing("timing", None)),
                  (READY, timing(cloud=True))):
        assert why(same_track(e, aiff(), rb, t)) is None


def test_another_format_needs_rekordbox_to_follow():
    e = entry(upgrade=parked())
    assert why(same_track(e, facts(), NONE, timeline_none())) is None  # no rekordbox: the file is a new track
    assert why(same_track(e, facts(), READY, timing("not_in_rekordbox"))) is None
    assert why(same_track(e, facts(), READY, timing("measured", 1105))) is None
    assert why(same_track(e, facts(), READY, None)) is None  # not measured yet: only the library's state counts
    assert why(same_track(e, facts(), UNREADABLE, None)) == "rekordbox_unreadable"
    assert why(same_track(e, facts(), READY, timing("unreadable", None))) == "rekordbox_unreadable"
    assert why(same_track(e, facts(), READY, timing(cloud=True))) == "cloud"
    assert why(same_track(e, facts(), READY, timing("not_analysed", None))) == "not_analysed"
    assert why(same_track(e, facts(), READY, timing("timing", None))) == "timing"


# --- Same track, quick (counts and screens: what is known without reading the file) ---

def test_quick_needs_a_parked_upgrade_that_is_the_same_edit_and_the_file_there():
    assert why(same_track_quick(entry(), READY)) == "no_upgrade"
    for result in ("different", "unknown", None):
        assert why(same_track_quick(entry(upgrade=parked(result)), READY)) == "needs_choice", result
    for result in ("exact", "shifted"):
        assert why(same_track_quick(entry(upgrade=parked(result)), READY)) is None, result
    e = entry(upgrade=parked())
    assert why(same_track_quick(e, READY, "away")) == "away"
    assert why(same_track_quick(e, READY, "missing")) == "file_missing"
    assert why(same_track_quick(entry(), READY, "missing")) == "no_upgrade"  # nothing waits: say that


def test_quick_lets_an_aiff_through_whatever_rekordbox_is_and_others_need_a_readable_library_or_none():
    for rb in (READY, NONE, UNREADABLE):
        assert why(same_track_quick(entry(upgrade=parked(), path="Library/Mine/x.AIFF"), rb)) is None
        assert why(same_track_quick(entry(upgrade=parked(), path="Library/Mine/x.aif"), rb)) is None
    for ext in (".mp3", ".m4a", ".flac", ".wav"):
        e = entry(upgrade=parked(), path=f"Library/Mine/x{ext}")
        assert why(same_track_quick(e, READY)) is None and why(same_track_quick(e, NONE)) is None, ext
        assert why(same_track_quick(e, UNREADABLE)) == "rekordbox_unreadable", ext
    busy = Status("ready", True, "7.0.0", "/rb/master.db", "busy", None, None)  # rekordbox runs and holds the file
    assert why(same_track_quick(entry(upgrade=parked()), busy)) is None  # the run decides: open rekordbox is its skip


@pytest.mark.parametrize("path", ["Library/Mine/x.mp3", "Library/Mine/x.aiff", None])
@pytest.mark.parametrize("rb", [READY, NONE, UNREADABLE])
@pytest.mark.parametrize("result", ["exact", "shifted", "different", None])
@pytest.mark.parametrize("present", ["here", "away", "missing"])
def test_quick_agrees_with_the_full_check_when_nothing_is_measured(path, rb, result, present):
    e = entry(upgrade=parked(result), path=path)
    ext = ".aiff" if path and path.endswith(".aiff") else ".mp3"
    full = same_track(e, facts(ext, "pcm_s16be" if ext == ".aiff" else "mp3"), rb, None, present=present)
    assert same_track_quick(e, rb, present) == full


def timeline_none():
    return TimelineOffset(0, "no_rekordbox", NONE, [])


# --- Convert to AIFF ---

def test_convert_is_for_the_users_own_files_only():
    assert why(convert(entry(), facts(), READY, None)) is None
    assert why(convert(entry(source="qobuz"), facts(), READY, None)) == "downloaded"
    assert why(convert(entry(source=None), facts(), READY, None)) == "downloaded"
    assert why(convert(entry(), facts(), READY, None, present="away")) == "away"
    assert why(convert(entry(), facts(), READY, None, present="missing")) == "file_missing"
    assert why(convert(entry(artist=" "), facts(), READY, None)) == "no_name"
    assert why(convert(entry(title=""), facts(), READY, None)) == "no_name"


def test_a_clean_aiff_needs_no_convert_but_anything_else_does():
    clean = aiff(tags={"title": "Song", "artist": "Artist"})
    assert why(convert(entry(), clean, READY, None)) == "clean_aiff"
    assert why(convert(entry(), facts(".aif", "pcm_s16be", 44100, 16, tags=TAGS), READY, None)) == "clean_aiff"
    for odd in (facts(".wav", "pcm_s16le", 44100, 16), facts(".flac", "flac", 44100, 16),
                facts(".aiff", "pcm_s24be", 44100, 24), facts(".aiff", "pcm_s16be", 48000, 16),
                aiff(tags={"title": "Other"}), aiff(tags={"artist": "Other"})):
        assert why(convert(entry(), odd, READY, None)) is None, odd
    # the album counts only where the record names one; an unlinked file's album is its own tag
    assert why(convert(entry(album="Right"), aiff(tags={"album": "Other"}), READY, None)) is None
    assert why(convert(entry(), aiff(tags={"album": "Other"}), READY, None)) == "clean_aiff"


def test_a_cover_the_record_has_is_part_of_clean():
    assert why(convert(entry(image_url="https://example.com/c.jpg"), aiff(cover=False), READY, None)) is None
    assert why(convert(entry(image_url="https://example.com/c.jpg"), aiff(cover=True), READY, None)) == "clean_aiff"
    assert why(convert(entry(), aiff(cover=False), READY, None)) == "clean_aiff"  # no cover wanted


def test_convert_follows_rekordbox_like_same_track():
    assert why(convert(entry(), facts(), UNREADABLE, None)) == "rekordbox_unreadable"
    assert why(convert(entry(), facts(), READY, timing(cloud=True))) == "cloud"
    assert why(convert(entry(), facts(), READY, timing("not_analysed", None))) == "not_analysed"
    assert why(convert(entry(), facts(), READY, timing("timing", None))) == "timing"
    assert why(convert(entry(), facts(), READY, timing("measured", 1105))) is None
    assert why(convert(entry(), facts(), NONE, timeline_none())) is None


# --- Give it its clean name ---

def test_rename_is_for_a_clean_own_aiff_with_another_name():
    e = entry(path="Library/Mine/track01.aiff")
    clean = aiff()
    target = "Library/Mine/Artist - Song.aiff"
    assert why(rename(e, clean, READY, None, clean_path=target)) is None
    assert why(rename(e, clean, READY, None, clean_path=target.upper())) is None
    assert why(rename(entry(path=target.lower()), clean, READY, None, clean_path=target)) == "named_already"
    assert why(rename(entry(path="Library/Mine/Artist - Song.aif"), facts(".aif", "pcm_s16be", 44100, 16), READY,
                      None, clean_path=target)) is None  # .aif becomes .aiff
    assert why(rename(e, facts(), READY, None, clean_path=target)) == "needs_convert"
    assert why(rename(e, aiff(tags={"title": "Other"}), READY, None, clean_path=target)) == "needs_convert"
    assert why(rename(e, None, READY, None, clean_path=target)) == "needs_convert"
    assert why(rename(entry(source="qobuz"), clean, READY, None, clean_path=target)) == "downloaded"
    assert why(rename(entry(artist=""), clean, READY, None, clean_path=None)) == "no_name"
    assert why(rename(e, clean, READY, None, present="away")) == "away"
    assert why(rename(e, clean, READY, None, present="missing")) == "file_missing"


def test_rename_follows_rekordbox_too():
    e = entry(path="Library/Mine/track01.aiff")
    assert why(rename(e, aiff(), UNREADABLE, None, clean_path="Library/Mine/Artist - Song.aiff")) == "rekordbox_unreadable"
    assert why(rename(e, aiff(), READY, timing(cloud=True), clean_path="Library/Mine/Artist - Song.aiff")) == "cloud"


def test_rename_keeps_the_audio_so_the_timeline_does_not_matter_to_it():
    e = entry(path="Library/Mine/track01.aiff")
    target = "Library/Mine/Artist - Song.aiff"
    for result in ("not_analysed", "timing"):
        assert why(rename(e, aiff(), READY, timing(result, None), clean_path=target)) is None, result
        assert why(convert(entry(), facts(), READY, timing(result, None))) == result  # Convert does change it
    assert why(rename(e, aiff(), READY, timing("unreadable", None), clean_path=target)) == "rekordbox_unreadable"


# --- the new file's tags ---

def test_expected_tags_take_the_record_first_and_the_old_file_for_the_rest():
    old = {**TAGS, "title": "old title", "album": "Old album", "label": "Old label", "isrc": "OLDISRC",
           "comment": "old comment"}
    got = expected_tags(entry(artist="A", artists=("A", "B"), title="New", album="New album", isrc="NEWISRC"), old)
    assert got["title"] == "New" and got["artist"] == "A, B"
    assert got["album"] == "New album" and got["isrc"] == "NEWISRC" and got["label"] == "Old label"
    got = expected_tags(entry(), old)
    assert (got["album"], got["isrc"]) == ("Old album", "OLDISRC")
    assert set(got) == set(TEXT_FIELDS)


def test_the_comment_is_the_quality_line_of_the_old_file():
    got = expected_tags(entry(source="manual", source_format="mp3", status="not_lossless", cutoff_hz=16000,
                              source_kbps=128), TAGS)
    assert got["comment"] == "bought file MP3 128 kbps · cutoff 16.0 kHz"
    assert expected_tags(entry(source=None), {**TAGS, "comment": "mine"})["comment"] == "mine"
    # the user's own file (source "manual", found by the import) reads as "Your own file (FORMAT)"
    got = expected_tags(entry(source="manual", source_format="flac", placed_by="import", status="lossless"), TAGS)
    assert got["comment"] == "Your own file (FLAC) · verified lossless"


def test_tags_clean_ignores_form_and_spaces():
    nfd = "Café"
    assert tags_clean(aiff(tags={"title": " Café ", "artist": "Artist"}), entry(title=nfd))
    assert not tags_clean(aiff(tags={"title": "Cafe"}), entry(title=nfd))
    assert tags_clean(aiff(tags={"artist": "A, B"}), entry(artist="A", artists=("A", "B")))
    assert not tags_clean(aiff(tags={"artist": "A"}), entry(artist="A", artists=("A", "B")))
    # label, ISRC and comment only add, they are never compared
    assert tags_clean(aiff(tags={"label": "x", "isrc": "y", "comment": "z"}), entry())


# --- text_plan: the user's own edits stay ---

def test_text_plan_writes_where_rekordbox_still_shows_the_files_tag():
    old = {**TAGS, "title": "Song (file)", "artist": "Artist (file)", "album": "Album (file)", "label": "L"}
    clean = {**TAGS, "title": "Song", "artist": "Artist", "album": "Album", "label": "L"}
    shown = row(title="Song (file)", artist="Artist (file)", album="Album (file)", label="L", isrc="", comment="")
    assert set(text_plan(shown, old, clean).values()) == {"write"}
    edited = row(title="My title", artist="Artist (file)", album="Album (file)", label="L", isrc="X", comment="gig")
    plan = text_plan(edited, old, clean)
    assert plan == {"title": "kept", "artist": "write", "album": "write", "label": "write", "isrc": "kept",
                    "comment": "kept"}
    assert fields_kept(edited, old, clean) == ["title", "isrc", "comment"]


def test_text_plan_treats_empty_and_missing_alike_and_a_value_already_clean_as_nothing_to_lose():
    assert set(text_plan(row(), {}, {}).values()) == {"write"}
    assert text_plan(row(title="  "), {**TAGS, "title": ""}, TAGS)["title"] == "write"
    clean = {**TAGS, "title": "Song"}
    assert text_plan(row(title="Song"), {**TAGS, "title": "Something else"}, clean)["title"] == "write"
    assert text_plan(row(title="Café"), {**TAGS, "title": "Café"}, clean)["title"] == "write"  # NFD vs NFC


# --- the comment: only Discjockey's own line is ever replaced ---

MIK = "1A - Energy 6"
OURS = "Qobuz FLAC · verified lossless"


def test_a_comment_of_the_users_own_stays_in_the_new_files_text():
    old = {**TAGS, "comment": MIK}
    assert expected_tags(entry(source="qobuz", source_format="flac"), old)["comment"] == MIK
    assert expected_tags(entry(source="manual", source_format="mp3"), old)["comment"] == MIK
    # empty, or a line Discjockey wrote itself: the quality line, as before
    assert expected_tags(entry(source="manual", source_format="mp3"), TAGS)["comment"] == "bought file MP3 · verified lossless"
    assert expected_tags(entry(source="manual", source_format="mp3"), {**TAGS, "comment": OURS})["comment"] == \
        "bought file MP3 · verified lossless"


def test_text_plan_writes_the_comment_only_over_nothing_or_discjockeys_own_line():
    old = {**TAGS, "comment": MIK}
    clean = {**TAGS, "comment": OURS}
    assert text_plan(row(comment=MIK), old, clean)["comment"] == "kept"           # Mixed In Key's: left alone
    assert text_plan(row(comment=MIK), old, {**TAGS, "comment": MIK})["comment"] == "write"   # nothing to change
    assert text_plan(row(comment=""), TAGS, clean)["comment"] == "write"
    assert text_plan(row(comment="  "), TAGS, clean)["comment"] == "write"
    ours_old = {**TAGS, "comment": "Qobuz FLAC · cutoff 16.0 kHz"}
    assert text_plan(row(comment="Qobuz FLAC · cutoff 16.0 kHz"), ours_old, clean)["comment"] == "write"
    assert text_plan(row(comment=OURS), TAGS, {**TAGS, "comment": "Qobuz FLAC · lossy"})["comment"] == "kept"


# --- stage D: a parked upgrade wins, and the one rule "make it a clean AIFF" (plan §0.1, §0.2) ---

TARGET = "Library/Mine/Artist - Song.aiff"


def test_a_parked_upgrade_makes_convert_and_rename_wait_for_same_track():
    up = parked("needs_choice")  # any parked upgrade, whatever its alignment says
    assert why(convert(entry(upgrade=up), facts(), READY, None)) == "upgrade_waits"
    assert why(rename(entry(path="Library/Mine/t.aiff", upgrade=up), aiff(), READY, None, clean_path=TARGET)) == "upgrade_waits"
    # the file's own refusals that come first still say what they said
    assert why(convert(entry(upgrade=up, source="qobuz"), facts(), READY, None)) == "downloaded"
    assert why(convert(entry(upgrade=up), facts(), READY, None, present="away")) == "away"
    assert why(convert(entry(upgrade=up, artist=""), facts(), READY, None)) == "no_name"
    assert why(convert(entry(upgrade=None), facts(), READY, None)) is None


def action(e, f, rb=READY, tm=None, **kw):
    kind, verdict = aiff_action(e, f, rb, tm, **kw)
    return kind, why(verdict)


def test_aiff_action_converts_what_convert_can_and_renames_what_only_rename_can():
    assert action(entry(), facts()) == ("convert", None)  # an MP3
    assert action(entry(), facts(".flac", "flac", 96000, 24)) == ("convert", None)
    assert action(entry(), aiff(tags={"title": "Other"})) == ("convert", None)  # wrong tags: a new file with new tags
    assert action(entry(), None) == ("convert", None)  # facts not known: the run reads them
    clean = aiff()
    assert action(entry(path="Library/Mine/t.aiff"), clean, clean_path=TARGET) == ("rename", None)
    assert action(entry(path=TARGET), clean, clean_path=TARGET) == ("rename", "named_already")  # Rename's answer


def test_aiff_action_gives_the_more_telling_skip():
    for e, f, expected in (
            (entry(source="qobuz"), facts(), "downloaded"),
            (entry(artist=""), facts(), "no_name"),
            (entry(upgrade=parked()), facts(), "upgrade_waits"),
            (entry(upgrade=parked()), aiff(), "upgrade_waits")):
        assert action(e, f, clean_path=TARGET) == ("convert", expected), expected
    assert action(entry(), facts(), present="away") == ("convert", "away")
    assert action(entry(), facts(), present="missing") == ("convert", "file_missing")
    assert action(entry(), facts(), rb=UNREADABLE) == ("convert", "rekordbox_unreadable")
    assert action(entry(), facts(), tm=timing(cloud=True)) == ("convert", "cloud")
    assert action(entry(), facts(), tm=timing("not_analysed", None)) == ("convert", "not_analysed")
    # a clean AIFF is not "clean_aiff" but what the name and rekordbox say
    e = entry(path="Library/Mine/t.aiff")
    assert action(e, aiff(), rb=UNREADABLE, clean_path=TARGET) == ("rename", "rekordbox_unreadable")
    assert action(e, aiff(), tm=timing(cloud=True), clean_path=TARGET) == ("rename", "cloud")
    assert action(e, aiff(), tm=timing("timing", None), clean_path=TARGET) == ("rename", None)  # audio untouched


def test_aiff_action_accepts_its_arguments_by_position():
    kind, verdict = aiff_action(entry(path="Library/Mine/t.aiff"), aiff(), READY, None, "here", TARGET)
    assert (kind, why(verdict)) == ("rename", None)


def test_which_codecs_are_lossless_for_make_all():
    for codec in ("pcm_s16be", "pcm_s16le", "pcm_s24le", "pcm_f32le", "flac", "alac"):
        assert is_lossless_codec(codec), codec
    for codec in ("mp3", "aac", "opus", "vorbis", "wmav2", "", None):
        assert not is_lossless_codec(codec), codec
