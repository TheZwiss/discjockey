"""Issue 43 E3a: the rules of the two actions for a missing file (`discjockey/missing.py`, plan §4.1) and their words
(§5.4): the action by song, `why_not` per reason, `will_words`, the item's `missing` object and the details' line and hint."""
from __future__ import annotations

from datetime import date

import pytest

from discjockey import missing
from discjockey.hub import outcomes
from discjockey.planner import ENTRY_KEYS

TODAY = date(2026, 11, 18)
SINCE = "2026-11-12T09:30:00"
PARKED = {"file": "Upgrades ready/A/x.aiff", "alignment": {"result": "exact"}}


def e(status="lossless", folder="A", in_playlists=True, **kw):
    entry = dict.fromkeys(ENTRY_KEYS)
    entry.update(aliases=[], artist="Artist", title="Song", duration_ms=180000, folder=folder, status=status,
                 path=None if status == "missing" else f"Library/{folder}/Artist - Song.aiff",
                 source=None if status == "missing" else "qobuz", rejected_sources=[], in_playlists=in_playlists)
    entry.update(kw)
    return entry


def gone(**kw):
    """A playlist song whose file waits as missing."""
    return e(**{"missing_since": SINCE, **kw})


def own(**kw):
    """The user's own song (a file of an import folder) whose file waits as missing."""
    return e(**{"folder": None, "in_playlists": False, "source": "manual", "missing_since": SINCE,
                "placed_by": "import", "path": "/Volumes/Example/Music/Artist - Song.aiff", **kw})


def state(_top=None, **tracks):
    """The records; `_top`: the keys beside the tracks (`never`, `ambiguous`)."""
    return {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}, **(_top or {})}


def place(path):
    return "Techno 2019" if path.startswith("Library/") else "Old crates"


def group(out, key="missing_file"):
    return next((g for g in out["groups"] if g["key"] == key), None)


# --- the rules (missing.py, plan §4.1) ---

def test_the_action_follows_the_song_not_a_choice():
    assert missing.action_for("sp1", gone()) == "download_again"
    assert missing.action_for("local:1", own()) == "remove"
    # an own key linked to a playlist song is a playlist song: Download again
    assert missing.action_for("local:2", own(in_playlists=True)) == "download_again"
    assert missing.ACTIONS == ("download_again", "remove")


@pytest.mark.parametrize("key,entry,action,extra,reason", [
    ("t1", e(), "download_again", {}, "not_missing"),                              # its file is back
    ("t1", e("missing", path=None), "download_again", {}, "not_missing"),          # no file row at all
    ("t1", gone(), "remove", {}, "wrong_action"),                                  # a playlist song gets no Remove
    ("local:1", own(), "download_again", {}, "wrong_action"),                      # an own song gets no Download again
    ("t1", gone(), "download_again", {"ambiguous": {"t1": ["a.aiff", "b.aiff"]}}, "found_twice"),
    ("t1", gone(), "download_again", {"never": {"t1": {}}}, "never"),
    ("t1", gone(file_gone="2026-11-18"), "download_again", {}, "asked"),
    ("local:1", own(rekordbox_check={"reason": "swapped"}), "remove", {}, "check_open"),
    ("t1", gone(), "download_again", {}, None),
    ("local:1", own(), "remove", {}, None),
])
def test_why_not_names_the_first_reason(key, entry, action, extra, reason):
    assert missing.why_not(key, entry, {**state(), **extra}, action) == reason


def test_found_twice_stops_only_download_again_and_check_open_only_remove():
    twice = {"ambiguous": {"local:1": ["a.aiff", "b.aiff"]}}
    assert missing.why_not("local:1", own(), twice, "remove") is None               # Remove may still run
    assert missing.why_not("t1", gone(rekordbox_check={"reason": "swapped"}), state(), "download_again") is None
    first = missing.why_not("t1", gone(file_gone="2026-11-18"), {"never": {"t1": {}}}, "download_again")
    assert first == "never"                                                        # the order of the plan's list


def test_every_reason_has_words_and_wrong_action_names_the_other_action():
    assert set(missing.REASONS) == {"not_missing", "wrong_action", "found_twice", "never", "check_open", "asked"}
    assert missing.reason_words("not_missing", "remove") == "Its file is back."
    assert missing.reason_words("wrong_action", "remove") == "This song gets Download again instead."
    assert missing.reason_words("wrong_action", "download_again") == "This song gets Remove from library instead."
    assert missing.reason_words("found_twice", "download_again") == (
        "Its file is in several places now: keep one and it links again.")
    assert missing.reason_words("never", "download_again") == "You chose Never download for it."
    assert missing.reason_words("check_open", "remove") == "Its rekordbox check is still open: finish it first."
    assert missing.reason_words("asked", "download_again") == "You asked for it already: it happens at your next sync."


def test_the_reasons_are_known_to_the_outcome_table_as_refused():
    for key in missing.REASONS:
        assert outcomes.REASONS[key].outcome == "refused" and outcomes.REASONS[key].text.endswith(".")


def test_will_words_say_which_of_the_outcomes_happens():
    assert missing.will_words("download_again", False) == "Downloads again at your next sync"
    assert missing.will_words("download_again", True) == (
        "Gets the better version already waiting for it at your next sync; nothing is downloaded")
    assert missing.will_words("remove", False) == "Removed from your library"
    assert missing.will_words("remove", True) == "Removed from your library"


def test_the_view_of_a_song_whose_file_is_not_missing_is_none():
    assert missing.view("t1", e(), state(), place, TODAY) is None
    assert missing.detail_view("t1", e(), state(), place, TODAY) is None


def test_the_view_carries_the_day_the_place_the_action_and_the_words():
    v = missing.view("t1", gone(), state(), place, TODAY)
    assert v == {"since": "2026-11-12", "place": "Techno 2019", "action": "download_again", "why_not": None,
                 "words": None, "will": "Downloads again at your next sync", "upgrade_waiting": False}
    parked = missing.view("t1", gone(upgrade=PARKED), state(), place, TODAY)
    assert parked["upgrade_waiting"] is True and parked["will"].startswith("Gets the better version")
    refused = missing.view("local:1", own(), state({"never": {"local:1": {}}}), place, TODAY)
    assert (refused["action"], refused["why_not"], refused["words"]) == ("remove", None, None)
    asked = missing.view("t1", gone(file_gone="2026-11-18"), state(), place, TODAY)
    assert (asked["why_not"], asked["words"]) == ("asked", missing.REASONS["asked"])
    assert missing.view("t1", gone(), state(), None, TODAY)["place"] == ""            # no place words: empty, not None


def test_the_item_line_says_since_when_and_where_it_was():
    assert missing.item_detail("t1", gone(), state(), place, TODAY) == "Missing since 12 Nov · was in Techno 2019"
    assert missing.item_detail("t1", gone(missing_since="2025-12-30T08:00:00"), state(), place, TODAY) == (
        "Missing since 30 Dec 2025 · was in Techno 2019")
    assert missing.item_detail("t1", gone(), state(), None, TODAY) == "Missing since 12 Nov"
    twice = state({"ambiguous": {"t1": ["Library/A/x.aiff", "/Volumes/Example/y.aiff"]}})
    assert missing.item_detail("t1", gone(), twice, place, TODAY) == "In 2 places now · keep one and it links again"


def test_the_details_line_and_hint_by_action():
    d = missing.detail_view("t1", gone(), state(), place, TODAY)
    assert d["line"] == "Not seen since 12 Nov. It was in Techno 2019."
    assert d["hint"] == ("Put the file back in any watched folder and it links again with everything it had. "
                         "Or download it again at your next sync.")
    d = missing.detail_view("t1", gone(upgrade=PARKED), state(), place, TODAY)
    assert d["hint"] == ("Put the file back in any watched folder and it links again with everything it had. "
                         "Or press Download again: the better version already waiting for it goes in at your next "
                         "sync, and nothing is downloaded.")
    d = missing.detail_view("local:1", own(), state(), place, TODAY)
    assert d["hint"] == ("Put the file back in any watched folder and it links again with everything it had. "
                         "Or remove the song from your library.")
    d = missing.detail_view("local:1", own(upgrade=PARKED), state(), place, TODAY)
    assert d["hint"].endswith("Or remove the song from your library. Its better version waiting in Upgrade ready "
                              "goes with it.")
    assert d["action"] == "remove" and d["upgrade_waiting"] is True       # the item's fields are in it too


def test_a_song_found_in_two_places_says_where_and_what_to_do():
    twice = state({"ambiguous": {"t1": ["Library/A/x.aiff", "/Volumes/Example/y.aiff"]}})
    d = missing.detail_view("t1", gone(), twice, place, TODAY)
    assert d["line"] == "Found in 2 places: Techno 2019 and Old crates."
    assert d["hint"] == "Delete or move away the copies you don't want; the one left links again."
    assert d["why_not"] == "found_twice"
    three = state({"ambiguous": {"t1": ["Library/A/x.aiff", "/V/y.aiff", "/V/z.aiff"]}})
    assert missing.detail_view("t1", gone(), three, place, TODAY)["line"] == (
        "Found in 3 places: Techno 2019, Old crates and Old crates.")
