"""discjockey/aiff_plan.py: the read-only plan behind Make all lossless files AIFF, a selection's Convert and the CDJ
group's Convert all (plan stage D §1.3, §5 D4). Pure Python on tmp_path libraries: files are empty stand-ins, the tag
reader is a fake that counts its calls, and nothing is decoded."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from discjockey import align, aiff_plan, audio, cdj, convert, db, library, quality, rbstep, rekordbox
from discjockey.audio import FileFacts
from discjockey.hub import views
from discjockey.library import Paths
from discjockey.planner import ENTRY_KEYS
from discjockey.playlists_file import Row
from discjockey.models import PlaylistRecord, RecordedTrack, WatchedFolder
from discjockey.rekordbox.master import Entry, Status

READY = Status("ready", False, "7.0.0", "/rb/master.db", None, "6000", "1")
RUNNING = Status("ready", True, "7.0.0", "/rb/master.db", None, "6000", "1")
NONE = Status("none", False, None, None, None, None, None)
UNREADABLE = Status("unreadable", False, None, "/rb/master.db", "key", None, None)
MINUTE = 60_000


def own(path: str, title: str, codec: str, rate: int = 44100, bits: int | None = None, kbps: int | None = None,
        **kw) -> dict:
    """A song of the user's own with its file's stored facts (a minute long), in no playlist."""
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Ann", title=title, duration_ms=MINUTE, folder=None, path=path, status="lossless",
             source="manual", placed_by="import", in_playlists=False, rejected_sources=[], upgrade=None,
             file_codec=codec, file_rate=rate, file_bits=bits, file_kbps=kbps)
    e.update(kw)
    return e


def aiff_facts(e: dict, **tags) -> FileFacts:
    """What the tag reader says of an AIFF 16/44.1: the song's own names unless `tags` change one."""
    text = {"title": e["title"], "artist": e["artist"], "album": "", "label": "", "isrc": "", "comment": ""}
    return FileFacts(".aiff", "pcm_s16be", 44100, 16, {**text, **tags}, True)


def row(**kw) -> Entry:
    base = dict(id="1", folder_path="/x", file_name="x", file_type=1, analysis_path=None, title="", artist="",
                album="", label="", isrc="", comment="", cloud=False, created_at=None, artist_id=None, album_id=None,
                label_id=None, org_folder_path="", local_folder_path=None, file_size=None, uuid=None)
    return Entry(**{**base, **kw})


class Reader:
    """The `tags` of a plan: serves `facts` by file name and remembers what it was asked."""

    def __init__(self, facts: dict[str, FileFacts]):
        self.facts = facts
        self.asked: list[str] = []

    def __call__(self, path: Path) -> FileFacts:
        self.asked.append(path.name)
        return self.facts[path.name]


def library_of(tmp_path: Path, tracks: dict[str, dict], absent: tuple[str, ...] = ()) -> tuple[Paths, dict]:
    """A music folder with an (empty-ish) file for every song, except the keys in `absent`."""
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    for key, e in tracks.items():
        if key not in absent and e.get("path"):
            file = paths.root / e["path"]
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"x" * 1000)
    return paths, {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}}


def add(paths: Paths, state: dict, key: str, e: dict) -> None:
    """One more song with its file."""
    state["tracks"][key] = e
    file = paths.root / e["path"]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"x" * 1000)


def songs() -> dict[str, dict]:
    """One own file of every kind a plan tells apart, all in Library/Mine."""
    flac = own("Library/Mine/a.flac", "Flac", "flac", 96000, 24)
    clean = own("Library/Mine/Ann - Clean.aiff", "Clean", "pcm_s16be", 44100, 16)
    return {
        "flac": flac,
        "wav": own("Library/Mine/b.wav", "Wav", "pcm_s24le", 44100, 24),
        "alac": own("Library/Mine/c.m4a", "Alac", "alac", 44100, 16),
        "hires": own("Library/Mine/d.aiff", "Hires", "pcm_s24be", 48000, 24),
        "tags": own("Library/Mine/e.aiff", "Tags", "pcm_s16be", 44100, 16),
        "name": own("Library/Mine/messy name.aiff", "Name", "pcm_s16be", 44100, 16),
        "clean": clean,
        "wavpack": own("Library/Mine/f.wv", "Wavpack", "wavpack", 44100, 16),
        "mp3": own("Library/Mine/g.mp3", "Mp3", "mp3", 44100, None, 320, status="not_lossless", cutoff_hz=19000),
        "aac": own("Library/Mine/h.m4a", "Aac", "aac", 44100, None, 420, status="not_lossless", cutoff_hz=19000),
        "up": own("Library/Mine/i.flac", "Up", "flac", 44100, 16,
                  upgrade={"file": "Upgrades ready/i.aiff", "alignment": {"result": "exact"}}),
        "noname": own("Library/Mine/j.flac", "", "flac", 44100, 16),
        "hidden": own("Library/Mine/k.m4a", "Hidden", "aac", 44100, None, 420, hidden=True, status="not_lossless"),
        "bought": {**own("Library/Mine/Ann - Bought.aiff", "Bought", "pcm_s16be", 44100, 16), "source": "qobuz",
                   "placed_by": None, "file_codec": None, "file_rate": None, "file_bits": None, "file_kbps": None},
    }


def reader(tracks: dict[str, dict]) -> Reader:
    facts = {}
    if "tags" in tracks:  # wrong title, on the clean name too (the chain case)
        facts["e.aiff"] = facts["Ann - Tags.aiff"] = aiff_facts(tracks["tags"], title="Wrong")
    for key, file in (("name", "messy name.aiff"), ("clean", "Ann - Clean.aiff")):
        if key in tracks:
            facts[file] = aiff_facts(tracks[key])
    return Reader(facts)


def run(paths, state, scope, rb=READY, entries: Callable | None = lambda file: [], **kw) -> aiff_plan.AiffPlan:
    kw.setdefault("tags", reader(state["tracks"]))
    return aiff_plan.plan(paths, state, scope, rb=rb, entries=entries, **kw)


def picked(*keys: str) -> dict:
    return {"kind": "tracks", "tracks": list(keys)}


def by_track(plan: aiff_plan.AiffPlan) -> dict[str, aiff_plan.Item]:
    return {i.track: i for i in plan.items}


@pytest.fixture
def lib(tmp_path):
    tracks = songs()
    paths, state = library_of(tmp_path, tracks)
    return paths, state


# --- a selection ---

def test_a_selection_picks_the_action_and_kind_of_every_file(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac", "wav", "alac", "hires", "tags", "name", "wavpack", "mp3", "aac"))
    items = by_track(plan)
    assert {k: (i.action, i.kind) for k, i in items.items()} == {
        "flac": ("convert", "flac"), "wav": ("convert", "wav"), "alac": ("convert", "alac"),
        "hires": ("convert", "aiff_hires"), "tags": ("convert", "tags"), "name": ("rename", "name"),
        "wavpack": ("convert", "wavpack"), "mp3": ("convert", "mp3"), "aac": ("convert", "aac")}
    assert [i.track for i in plan.items] == ["flac", "wav", "alac", "hires", "tags", "name", "wavpack", "mp3", "aac"]
    assert plan.total == 9 and plan.skipped == ()


def test_the_kinds_come_in_kind_order_with_their_words_and_counts(lib):
    paths, state = lib
    plan = run(paths, state, picked("aac", "mp3", "name", "wavpack", "tags", "hires", "alac", "wav", "flac"))
    assert [(k["kind"], k["label"], k["n"]) for k in plan.kinds] == [
        ("flac", "FLAC → AIFF", 1), ("wav", "WAV → AIFF", 1), ("alac", "ALAC → AIFF", 1),
        ("aiff_hires", "AIFF 24-bit or above 44.1 kHz → 16-bit", 1), ("tags", "New tags", 1),
        ("name", "Clean name only", 1), ("wavpack", "WavPack → AIFF", 1), ("mp3", "MP3 → AIFF", 1),
        ("aac", "AAC → AIFF", 1)]
    assert aiff_plan.KIND_ORDER.index("tags") < aiff_plan.KIND_ORDER.index("name") < aiff_plan.KIND_ORDER.index("mp3")


def test_two_files_of_one_kind_count_once_in_their_kind(lib):
    paths, state = lib
    add(paths, state, "flac2", own("Library/Mine/a2.flac", "Flac Two", "flac", 44100, 16))
    plan = run(paths, state, picked("flac", "flac2", "wav"))
    assert [(k["kind"], k["n"]) for k in plan.kinds] == [("flac", 2), ("wav", 1)]


def test_an_unusual_codec_is_its_own_kind_after_the_listed_ones(lib):
    paths, state = lib
    add(paths, state, "wma", own("Library/Mine/w.wma", "Wma", "wmav2", 44100, None, 192, status="not_lossless"))
    plan = run(paths, state, picked("wma", "aac", "flac"))
    assert [k["kind"] for k in plan.kinds] == ["flac", "aac", "wmav2"]
    assert plan.kinds[-1]["label"] == "WMA → AIFF"


def test_the_lossy_count_is_the_files_whose_codec_is_not_lossless(lib):
    paths, state = lib
    assert run(paths, state, picked("flac", "mp3", "aac", "name", "wavpack")).lossy == 2
    assert run(paths, state, picked("flac", "name")).lossy == 0
    assert by_track(run(paths, state, picked("mp3")))["mp3"].lossy is True


def test_files_with_nothing_to_do_are_skipped_with_their_words_in_a_selection(lib):
    paths, state = lib
    plan = run(paths, state, picked("clean", "bought", "up", "noname", "flac"))
    assert [i.track for i in plan.items] == ["flac"]
    assert {s.track: s.reason for s in plan.skipped} == {
        "clean": "named_already", "bought": "downloaded", "up": "upgrade_waits", "noname": "no_name"}
    left = {s.track: s for s in plan.skipped}
    assert left["clean"].message == rbstep.CONVERT_REFUSED["named_already"]
    assert left["up"].message == "A better version is waiting: Same track makes it an AIFF."
    assert left["clean"].name == "Ann - Clean" and left["noname"].name == "Ann - "


def test_a_missing_file_a_missing_drive_and_an_unknown_track_are_skipped(tmp_path):
    tracks = songs()
    tracks["gone"] = own("/Volumes/Nowhere Drive/Music/x.flac", "Gone", "flac", 44100, 16)
    paths, state = library_of(tmp_path, {**tracks, "absent": own("Library/Mine/z.flac", "Absent", "flac", 44100, 16)},
                              absent=("absent", "gone"))
    plan = run(paths, state, picked("absent", "gone", "nobody", "flac"))
    assert [(s.track, s.reason) for s in plan.skipped] == [
        ("absent", "file_missing"), ("gone", "away"), ("nobody", "file_missing")]
    assert plan.skipped[2].name == "nobody"
    assert [i.track for i in plan.items] == ["flac"]


def test_a_track_picked_twice_counts_once(lib):
    paths, state = lib
    assert [i.track for i in run(paths, state, picked("flac", "flac", "wav")).items] == ["flac", "wav"]


def test_the_item_says_what_the_file_is_where_it_goes_and_what_it_costs(lib):
    paths, state = lib
    flac, name = (by_track(run(paths, state, picked("flac", "name")))[k] for k in ("flac", "name"))
    assert (flac.name, flac.source, flac.path) == ("Ann - Flac", "FLAC · 24-bit · 96 kHz", "Library/Mine/a.flac")
    assert flac.new_path == "Library/Mine/Ann - Flac.aiff"
    assert flac.superseded == "Superseded/Mine/a.flac"
    assert flac.bytes == convert.needed_bytes(60, 2) and flac.old_bytes == 1000
    assert (name.source, name.new_path, name.superseded, name.bytes) == (
        "AIFF · 16-bit · 44.1 kHz", "Library/Mine/Ann - Name.aiff", None, 0)
    assert by_track(run(paths, state, picked("mp3")))["mp3"].source == "MP3 · 44.1 kHz · 320 kbps"


def test_two_files_that_want_one_name_are_told_apart(lib):
    paths, state = lib
    add(paths, state, "twin", own("Library/Mine/a-twin.flac", "Flac", "flac", 44100, 16))
    items = by_track(run(paths, state, picked("flac", "twin")))
    assert items["flac"].new_path == "Library/Mine/Ann - Flac.aiff"
    assert items["twin"].new_path.startswith("Library/Mine/Ann - Flac ") and items["twin"].new_path != items["flac"].new_path


def test_an_aiff_that_holds_its_clean_name_ends_there_after_the_chain(lib):
    """Wrong tags on the clean name: the new AIFF takes the ID, then the file is renamed to the clean name, so it ends
    where the old one was and the old one goes to Superseded/."""
    paths, state = lib
    state["tracks"]["tags"]["path"] = "Library/Mine/Ann - Tags.aiff"
    paths.root.joinpath("Library/Mine/Ann - Tags.aiff").write_bytes(b"x" * 1000)
    item = by_track(run(paths, state, picked("tags")))["tags"]
    assert (item.action, item.kind, item.path, item.new_path) == (
        "convert", "tags", "Library/Mine/Ann - Tags.aiff", "Library/Mine/Ann - Tags.aiff")
    assert item.superseded == "Superseded/Mine/Ann - Tags.aiff" and item.bytes > 0


def test_a_file_whose_facts_are_not_stored_yet_is_read_once_in_a_selection_only(lib):
    paths, state = lib
    for k in ("flac", "wav"):
        for key in ("file_codec", "file_rate", "file_bits", "file_kbps"):
            state["tracks"][k][key] = None
    tags = reader(state["tracks"])
    tags.facts["a.flac"] = FileFacts(".flac", "flac", 96000, 24, {}, False)
    tags.facts["b.wav"] = FileFacts(".wav", "pcm_s24le", 44100, 24, {}, False)
    plan = run(paths, state, picked("flac", "wav"), tags=tags)
    assert [(i.track, i.kind) for i in plan.items] == [("flac", "flac"), ("wav", "wav")]
    assert tags.asked == ["a.flac", "b.wav"]
    # the all scopes work from what is stored: a file without facts is not in "lossless"
    tags.asked.clear()
    plan = run(paths, state, {"kind": "lossless", "view": "all"}, tags=tags)
    assert "flac" not in by_track(plan) and "wav" not in by_track(plan)


def test_a_file_that_cannot_be_read_is_skipped_in_a_selection(lib):
    paths, state = lib
    for key in ("file_codec", "file_rate", "file_bits", "file_kbps"):
        state["tracks"]["flac"][key] = None

    def broken(path):
        raise RuntimeError("no audio")
    plan = run(paths, state, picked("flac", "wav"), tags=broken)
    assert [(s.track, s.reason) for s in plan.skipped] == [("flac", "file_missing")]
    assert [i.track for i in plan.items] == ["wav"]


# --- what is read ---

def test_only_an_own_aiff_in_the_library_format_has_its_tags_read(lib):
    paths, state = lib
    tags = reader(state["tracks"])
    run(paths, state, picked("flac", "wav", "alac", "hires", "mp3", "bought", "tags", "name", "clean"), tags=tags)
    assert sorted(tags.asked) == ["Ann - Clean.aiff", "e.aiff", "messy name.aiff"]


def test_the_plan_never_decodes_and_changes_nothing(lib, monkeypatch):
    paths, state = lib

    def boom(*args, **kwargs):
        raise AssertionError("the plan decoded or measured a file")
    monkeypatch.setattr(align, "compare_files", boom)
    monkeypatch.setattr(rekordbox, "timeline_offset", boom)
    monkeypatch.setattr(quality, "analyze", boom)
    monkeypatch.setattr(quality, "decode_mono", boom)
    monkeypatch.setattr(audio, "write_tags", boom)
    library.open_records(paths)
    before = fingerprint(paths)
    db_before = hashlib.sha256(paths.db_file.read_bytes()).hexdigest()
    state_before = repr(state)
    for scope in (picked(*state["tracks"]), {"kind": "lossless", "view": "all"}, {"kind": "cdj"}):
        run(paths, state, scope, entries=lambda file: [row()])
    assert fingerprint(paths) == before and repr(state) == state_before
    assert hashlib.sha256(paths.db_file.read_bytes()).hexdigest() == db_before


def fingerprint(paths: Paths) -> dict[str, tuple]:
    out = {}
    for p in sorted(paths.root.rglob("*")):
        if p.is_file():
            stat = p.stat()
            out[p.relative_to(paths.root).as_posix()] = (stat.st_size, stat.st_mtime_ns,
                                                         hashlib.sha256(p.read_bytes()).hexdigest())
    return out


# --- Make all lossless files AIFF: the views ---

def lossless(view="all", key=None) -> dict:
    return {"kind": "lossless", "view": view, "key": key}


def test_lossless_covers_every_file_of_the_view_whose_codec_is_lossless(lib):
    paths, state = lib
    plan = run(paths, state, lossless())
    assert [i.track for i in plan.items] == ["flac", "wav", "alac", "hires", "tags", "name", "wavpack"]
    assert plan.scope == {"kind": "lossless", "view": "all", "key": None, "label": "All tracks"}


def test_lossless_is_only_lossless_and_leaves_out_what_has_nothing_to_do_without_a_skipped_list(lib):
    paths, state = lib
    plan = run(paths, state, lossless())
    items = by_track(plan)
    assert set(items) == {"flac", "wav", "alac", "hires", "tags", "name", "wavpack"}
    # lossy files, a clean AIFF with its name, a download, a parked upgrade and a song with no name are left out
    for key in ("mp3", "aac", "clean", "bought", "up", "noname", "hidden"):
        assert key not in items
    assert plan.skipped == () and plan.lossy == 0


def test_wavpack_ape_and_tta_count_as_lossless_for_make_all_and_the_cdj_group_still_flags_them(lib):
    paths, state = lib
    add(paths, state, "ape", own("Library/Mine/l.ape", "Ape", "ape", 44100, 16))
    add(paths, state, "tta", own("Library/Mine/m.tta", "Tta", "tta", 44100, 16))
    items = by_track(run(paths, state, lossless()))
    assert {"wavpack", "ape", "tta"} <= set(items)
    group = cdj.group_members(state)
    assert {"wavpack", "ape", "tta"} <= set(group) and {group[k].reason for k in ("wavpack", "ape", "tta")} == {"format"}


def membership(state: dict, view: str, key: str | None, **kw) -> list[str]:
    """What `views.library` lists for the view (rows with a file, then `also`), with no filter and no search."""
    out = views.library(state, view, key, "", "all", None, **kw)
    return [r["track_id"] for r in [*out["rows"], *(out["also"] or [])] if r["file_state"] != "no_file"]


def view_state(sets: str = "/Users/dj/Sets") -> dict:
    """Techno holds a (own folder) and b (own folder, in not_lossless/), c sits in House's folder, g has no file,
    d sits in Techno's folder without the playlist holding it; two import-folder files, one of them in a playlist."""
    def song(folder, name, path, **kw):
        return {**own(path, name, "flac", 44100, 16, folder=folder), "in_playlists": True, **kw}
    tracks = {
        "a": song("Techno", "One", "Library/Techno/Ann - One.flac"),
        "b": song("Techno", "Two", "Library/Techno/not_lossless/Ann - Two.flac"),
        "c": song("Techno", "Three", "Library/House/Ann - Three.flac"),
        "d": song("Techno", "Four", "Library/techno/Ann - Four.flac", in_playlists=False),
        "g": {**song("Techno", "Gone", "Library/Techno/x.flac"), "status": "missing", "path": None},
        "local:1": own(f"{sets}/Hard/Ann - Five.flac", "Five", "flac", 44100, 16),
        "local:2": own("Library/Techno/Ann - Six.flac", "Six", "flac", 44100, 16)}
    return {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}}


TECHNO = Row("Techno", "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd")
HOUSE = Row("House", "https://open.qobuz.com/playlist/900000001")
LINES = [TECHNO, HOUSE]
RECORDS = {TECHNO.ref: PlaylistRecord("spotify", "2026-10-30T10:00:00", tuple(
    RecordedTrack(i, t, "Ann", f"T {t}", 1000) for i, t in enumerate(("a", "b", "a", "c", "g", "unheard"), start=1)))}


@pytest.mark.parametrize("view, key", [("all", None), ("unlisted", None), ("playlist", "Techno"),
                                       ("playlist", "techno"), ("playlist", "House"), ("playlist", "Nowhere"),
                                       ("folder", "Library/Techno"), ("folder", "Library/Techno/not_lossless"),
                                       ("folder", "Library/Nowhere")])
def test_the_view_membership_is_what_the_library_lists(view, key):
    state = view_state()
    expected = membership(state, view, key, lines=LINES, records=RECORDS)
    found = views.library_files(state, view, key, lines=LINES, records=RECORDS)
    assert sorted(found.keys) == sorted(expected) and len(set(found.keys)) == len(found.keys)
    assert found.title == views.library(state, view, key, "", "all", None, lines=LINES, records=RECORDS)["title"]


def test_a_playlists_files_are_its_songs_in_order_then_its_own_folders_others():
    found = views.library_files(view_state(), "playlist", "Techno", lines=LINES, records=RECORDS)
    assert found.keys == ["a", "b", "c", "d", "local:2"] and found.title == "Techno"


def test_a_watched_folders_files_are_the_ones_below_it():
    watched = [WatchedFolder(2, Path("/Users/dj/Sets"), "import")]
    found = views.library_files(view_state(), "folder", "/Users/dj/Sets", lines=LINES, watched=watched)
    assert found.keys == ["local:1"] and found.title == "Sets"
    assert found.keys == membership(view_state(), "folder", "/Users/dj/Sets", lines=LINES, watched=watched)


def test_the_filter_and_the_search_do_not_narrow_the_set(tmp_path):
    """Make all means the view, not what the table shows: the plan has no filter or search to ask."""
    tracks = {"a": own("Library/Techno/Ann - One.flac", "One", "flac", 44100, 16),
              "b": own("Library/Techno/Ann - Two.flac", "Two", "flac", 44100, 16, status="fake_lossless")}
    paths, state = library_of(tmp_path, tracks)
    narrowed = views.library(state, "folder", "Library/Techno", "one", "lossless", None, lines=[])
    assert [r["track_id"] for r in narrowed["rows"]] == ["a"]
    plan = run(paths, state, lossless("folder", "Library/Techno"))
    assert sorted(i.track for i in plan.items) == ["a", "b"] and plan.scope["label"] == "Techno"


@pytest.mark.parametrize("view, key, label, tracks", [
    ("all", None, "All tracks", ["a", "b", "c", "d", "local:1", "local:2"]),
    ("unlisted", None, "Not in a playlist", ["local:1", "local:2", "d"]),
    ("playlist", "Techno", "Techno", ["a", "b", "c", "d", "local:2"]),
    ("folder", "Library/House", "House", ["c"])])
def test_lossless_over_a_view_plans_that_views_files(tmp_path, view, key, label, tracks):
    paths, state = library_of(tmp_path, view_state(str(tmp_path / "Sets"))["tracks"])
    plan = run(paths, state, lossless(view, key), lines=LINES, records=RECORDS, watched=[])
    assert sorted(i.track for i in plan.items) == sorted(tracks) and plan.scope["label"] == label


def test_a_view_needs_its_key_and_a_scope_its_kind(lib):
    paths, state = lib
    for bad in ({"kind": "lossless", "view": "playlist"}, {"kind": "lossless", "view": "folder", "key": ""},
                {"kind": "lossless", "view": "elsewhere"}, {"kind": "everything"}):
        with pytest.raises(ValueError):
            run(paths, state, bad)


def test_the_playlist_and_watched_folder_inputs_are_read_from_the_library_when_not_given(tmp_path):
    paths, state = library_of(tmp_path, view_state(str(tmp_path / "Sets"))["tracks"])
    paths.playlists_file.parent.mkdir(parents=True, exist_ok=True)
    paths.playlists_file.write_text(f"Techno = {TECHNO.link}\n")
    library.open_records(paths)
    record = RECORDS[TECHNO.ref]
    with db.connect(paths.db_file) as conn, db.transaction(conn):
        conn.execute("INSERT INTO playlist_reads (playlist, service, read_at) VALUES (?, ?, ?)",
                     (TECHNO.ref, record.service, record.read_at))
        conn.executemany("INSERT INTO playlist_tracks (playlist, position, token, artist, title, duration_ms) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         [(TECHNO.ref, t.position, t.token, t.artist, t.title, t.duration_ms) for t in record.tracks])
    plan = run(paths, state, lossless("playlist", "Techno"))
    assert sorted(i.track for i in plan.items) == ["a", "b", "c", "d", "local:2"]


# --- Convert all (the CDJ group) ---

def test_the_cdj_scope_is_the_cdj_group(lib):
    paths, state = lib
    group = cdj.group_members(state)
    assert set(group) == {"wavpack", "aac"}  # hidden, a parked upgrade, a download and facts not stored: not in it
    plan = run(paths, state, {"kind": "cdj"})
    assert [i.track for i in plan.items] == list(group)
    assert plan.scope == {"kind": "cdj", "label": "Won't play well on CDJs"} and plan.skipped == ()
    aac = by_track(plan)["aac"]
    assert aac.cdj == {"short": "AAC 420 kbps · CDJs stop at 320", "words": group["aac"].words}


def test_the_group_is_own_files_with_a_problem_no_parked_upgrade_and_not_hidden(lib):
    paths, state = lib
    state["tracks"]["hidden"]["hidden"] = False
    assert "hidden" in cdj.group_members(state)
    state["tracks"]["aac"]["upgrade"] = {"file": "x"}
    assert "aac" not in cdj.group_members(state)
    state["tracks"]["aac"]["upgrade"] = None
    state["tracks"]["aac"]["file_codec"] = None
    assert "aac" not in cdj.group_members(state)
    state["tracks"]["aac"].update(file_codec="aac", source="qobuz")
    assert "aac" not in cdj.group_members(state)
    state["tracks"]["aac"].update(source="manual", status="missing", path=None)
    assert "aac" not in cdj.group_members(state)


def test_an_item_carries_the_cdj_words_in_any_scope_when_the_file_has_a_problem(lib):
    paths, state = lib
    items = by_track(run(paths, state, picked("aac", "flac", "wavpack")))
    assert items["flac"].cdj is None
    assert items["wavpack"].cdj == {"short": "WavPack · CDJs don't play it", "words": "CDJs don't play WavPack files."}
    assert items["aac"].cdj["short"].startswith("AAC 420 kbps")


# --- space ---

def test_the_room_needed_is_one_row_per_drive(lib, monkeypatch):
    paths, state = lib
    monkeypatch.setattr(convert, "free_space", lambda folder: 5 * convert.needed_bytes(60, 2))
    plan = run(paths, state, picked("flac", "wav", "name"))
    one = convert.needed_bytes(60, 2)
    assert len(plan.space) == 1 and (plan.space[0]["needed"], plan.space[0]["free"]) == (2 * one, 5 * one)
    assert plan.space[0]["enough"] is True and Path(plan.space[0]["drive"]).is_relative_to(paths.root)
    monkeypatch.setattr(convert, "free_space", lambda folder: one)
    assert run(paths, state, picked("flac", "wav")).space[0]["enough"] is False
    assert run(paths, state, picked("name")).space == ()  # a Rename needs no room


def test_a_second_drive_counts_its_new_files_and_the_biggest_render_on_the_work_drive(tmp_path, monkeypatch):
    tracks = {"a": own("Library/Other/a.flac", "A", "flac", 44100, 16),
              "b": own("Library/Other/b.flac", "B", "flac", 44100, 16, duration_ms=2 * MINUTE),
              "c": own("Library/Mine/c.flac", "C", "flac", 44100, 16)}
    paths, state = library_of(tmp_path, tracks)
    monkeypatch.setattr(library, "device", lambda p: 2 if "Other" in Path(p).parts else 1)
    free = {1: 10**12, 2: 10**6}
    monkeypatch.setattr(convert, "free_space", lambda folder: free[2 if "Other" in folder.parts else 1])
    plan = run(paths, state, picked("a", "b", "c"))
    one, two = convert.needed_bytes(60, 2), convert.needed_bytes(120, 2)
    drives = {Path(s["drive"]).is_relative_to(paths.root / "Library/Other"): s for s in plan.space}
    other, work = drives[True], drives[False]
    assert (other["needed"], other["free"], other["enough"]) == (one + two, 10**6, False)
    # the work drive holds one render at a time (the biggest) and the new file that stays on it
    assert (work["needed"], work["enough"]) == (max(two, one), True)
    assert work["needed"] == two + 0 and len(plan.space) == 2


def test_the_originals_that_go_to_superseded_are_summed(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac", "wav", "name"))
    assert plan.superseded_bytes == 2000  # the Rename's file stays where it is


# --- rekordbox ---

def closed(plan: aiff_plan.AiffPlan) -> bool:
    return plan.rekordbox["needs_closed"]


def test_rekordbox_is_not_needed_closed_without_a_library_or_a_track(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac"), rb=NONE, entries=None)
    assert plan.rekordbox == {"state": "none", "running": False, "needs_closed": False}
    assert closed(run(paths, state, picked("flac"), rb=READY, entries=lambda file: [])) is False


def test_rekordbox_must_be_closed_when_a_file_of_the_plan_is_in_it(lib):
    paths, state = lib
    held = paths.root / "Library/Mine/b.wav"
    plan = run(paths, state, picked("flac", "wav"), rb=RUNNING, entries=lambda file: [row()] if file == held else [])
    assert plan.rekordbox == {"state": "ready", "running": True, "needs_closed": True}
    # a file rekordbox holds that the plan leaves alone doesn't count
    assert closed(run(paths, state, picked("flac", "up"), entries=lambda file: [row()] if file.name == "i.flac" else [])) is False


def test_a_rename_of_a_file_in_rekordbox_needs_it_closed_too(lib):
    paths, state = lib
    assert closed(run(paths, state, picked("name"), entries=lambda file: [row()])) is True


def test_a_library_that_cannot_be_read_may_hold_any_file_so_the_run_decides(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac", "name", "clean"), rb=UNREADABLE, entries=None)
    assert [i.track for i in plan.items] == ["flac", "name"] and closed(plan) is True
    assert plan.rekordbox["state"] == "unreadable" and plan.skipped[0].reason == "named_already"
    assert closed(run(paths, state, picked("clean"), rb=UNREADABLE, entries=None)) is False  # nothing to run


def test_a_track_in_cloud_library_sync_is_skipped(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac", "wav"), entries=lambda file: [row(cloud=True)] if file.name == "a.flac" else [])
    assert [i.track for i in plan.items] == ["wav"]
    assert [(s.track, s.reason) for s in plan.skipped] == [("flac", "cloud")]


# --- the shape ---

def test_to_dict_is_the_bridges_one_shape(lib):
    paths, state = lib
    plan = run(paths, state, picked("flac", "name", "clean"))
    out = plan.to_dict()
    assert list(out) == ["scope", "items", "skipped", "kinds", "lossy", "total", "space", "superseded_bytes",
                         "rekordbox"]
    assert out["scope"] == {"kind": "tracks", "tracks": ["flac", "name", "clean"], "label": "Selection"}
    assert list(out["items"][0]) == ["track", "name", "action", "kind", "from", "path", "new_path", "superseded",
                                     "bytes", "cdj"]
    assert list(out["skipped"][0]) == ["track", "name", "reason", "message"]
    assert list(out["space"][0]) == ["drive", "needed", "free", "enough"]
    assert list(out["rekordbox"]) == ["state", "running", "needs_closed"]
    assert (out["total"], out["lossy"], out["superseded_bytes"]) == (2, 0, 1000)
    assert plan.actions() == [("flac", "convert"), ("name", "rename")]


def test_an_empty_plan_has_the_whole_shape(lib):
    paths, state = lib
    out = run(paths, state, lossless("folder", "Library/Nowhere")).to_dict()
    assert (out["items"], out["skipped"], out["kinds"], out["space"], out["total"], out["lossy"]) == ([], [], [], [], 0, 0)
    assert out["rekordbox"]["needs_closed"] is False
