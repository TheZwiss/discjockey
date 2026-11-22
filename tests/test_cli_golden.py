"""The golden and parity harnesses (issue 39, plan v2 §3.1): one parametrised test per built read entry of the
catalogue. A group that builds a read gives its entry an `example` (the command line to run on the fixture) and gets
all three for free:

* golden: the text page equals `tests/cli_golden/<noun>_<verb>.txt` (`UPDATE_GOLDEN=1` writes it; a reviewer reads the
  diff to see the page);
* T7': every leaf of `data`, as the printer writes it, occurs in the text with `--verbose` (pages may reorder and
  word, never drop);
* T4: `--json`'s `data` equals the bridge's answer minus `ok` (and `next`, which the envelope carries)."""
import base64
import json
import os
import re
import shlex
import shutil
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from hub_helpers import LOSSLESS, LOSSY, choose_music, make_root, stub_headless
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import db, library, pending_signs, tools
from test_cli_batches import with_batches, with_report
from test_cli_missing import missing_library
from test_cli_reads import rich_library
from discjockey.cli import bind, call, parser
from discjockey.cli.render import generic
from discjockey.hub import catalog

GOLDEN = Path(__file__).parent / "cli_golden"
READS = [e for e in parser.built() if e.kind == "R"]
WRITES = ["library_facts", "aiff_convert", "aiff_rename", "upgrade_apply", "upgrade_discard", "track_undo", "check_done", "batch_resume", "batch_undo", "rekordbox_restore", "sync_run", "folder_add", "folder_remove", "settings_set", "missing_download", "missing_remove", "sync_scope_off"]  # the writes with a golden page (their own tests run them: tests/test_cli_upgrade.py)


GOLDEN_NAMES = {"undo_preview": "batch_undo_moves"}  # a read whose command has a write with a page of its own: `batch undo`'s AIFF write has batch_undo.txt


def golden_name(entry) -> str:
    """The file of a read's page under `tests/cli_golden`, without `.txt`: its command's words, unless the command is
    shared with a write that has a page (`GOLDEN_NAMES`)."""
    return GOLDEN_NAMES.get(entry.method, "_".join(entry.command))


TIMED = {("limits", "show"), ("limits", "set"), ("status",)}  # pages that word today's date: on the fixed clock of `services()`
STUBBED = {("setup", "status"), ("tools", "status"), ("login", "list"), ("login", "find"), ("app", "info"),
           ("doctor",), ("status",)}  # reads of this Mac
RICH = {("todo", "list"), ("upgrade", "list"), ("check", "list"), ("track", "show")}  # reads that need a better version
                                                                                        # parked and checks open
CLICKS = Path(__file__).parent / "fixtures" / "clicks-lame.mp3"  # the one real audio file: a preview decodes it


def skip_without_tools(entry):
    """`rekordbox preview` and `track spectrum` decode a real file: without ffmpeg and ffprobe they skip, like the other
    audio tests."""
    if entry.method in ("rekordbox_preview", "spectrum") and (shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None):
        pytest.skip("ffmpeg not installed")


MASTER_TIME = 1_700_000_000  # master.db's modified time in the fixture: a fixed one, in UTC, so its page is the same everywhere


@pytest.fixture
def utc():
    """The page of `rekordbox status` words master.db's modified time in local time: UTC for the golden."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


def with_read(paths, monkeypatch):
    """The playlists read the hub fixture's two lines hold (two songs to download: `sync plan` has a plan to show), made
    on the clock of `hub_helpers.services()` (2026-10-20 21:47), which the command line's api now runs on: the page
    words the read's age and the plan's days, so it must not move with the day it runs on."""
    from datetime import datetime

    from hub_helpers import ID1, ID2, TRACKS, store_sync_read

    from discjockey.models import FetchedPlaylist, PlaylistLine
    store_sync_read(paths, [FetchedPlaylist(PlaylistLine("Hard_Bounce", ID1, 2), TRACKS[ID1], []),
                            FetchedPlaylist(PlaylistLine("Powertrance", ID2, 3), TRACKS[ID2], [])],
                    when=datetime(2026, 10, 20, 21, 45))
    with_clock(monkeypatch)


def with_clock(monkeypatch):
    """The command line's api on the services of the hub fixtures (`hub_helpers.services()`: the clock is 2026-10-20 21:47,
    nothing of this Mac): a page that words the date or an age must not move with the day it runs on."""
    from hub_helpers import services

    from discjockey.hub.api import CliApi

    def default():
        resolved = library.resolve_paths()
        api = CliApi(resolved.support, None, services())
        api._attach(resolved.paths)
        return api
    monkeypatch.setattr(bind, "default", default)


def with_backups(tmp_path, monkeypatch):
    """Two backups of the fixture rekordbox library, made at fixed times (their names are the time), one of them by two
    batches: what `rekordbox backups` lists."""
    from datetime import UTC, datetime

    from discjockey.rekordbox import backup as rb_backup
    from discjockey.rekordbox.locate import Place
    folder = tmp_path / "rekordbox"
    place = Place(folder / "master.db", folder / "share", "override", None)
    paths = library.resolve_paths().paths
    monkeypatch.setattr(rb_backup, "__version__", "0")  # the manifest holds the app's version: its size must not move
    for batch, stamp in ((1, datetime(2026, 11, 10, 9, 0, 1, tzinfo=UTC)), (2, datetime(2026, 11, 12, 18, 30, 0, tzinfo=UTC))):
        rb_backup.Backup.ensure(paths, place, dbid=None, batch_id=batch, tracks=[], now=lambda stamp=stamp: stamp)


DOCTORS = {("doctor",), ("status",)}  # a read that needs something wrong to say: a watched drive that is away, a pause waiting


def with_doctor(paths) -> None:
    """A watched folder on a drive that is not connected (a problem with a step) and a YouTube pause waiting for the
    lock (a note), so the page shows both with their next steps."""
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, Path("/Volumes/Example Stick/Crates"), datetime(2026, 11, 20, 9, 0))
    pending_signs.add(paths, [("youtube", "auto_stop", "YouTube asked for a pause")], datetime.now())


MATCHES = {("rekordbox", "match"), ("library", "superseded")}  # reads that need rekordbox tracks and files in Superseded/


def with_match(paths) -> list[dict]:
    """Two files in Superseded/ (rekordbox points at one) and a rekordbox track of each kind of `rekordbox match`
    besides the song's: the rows for `make_master`. The hub fixture's lossless song is held, the lossy one is not."""
    held = {"Superseded/Hard_Bounce/Old.mp3": 1_200_000, "Superseded/Hard_Bounce/Spare.mp3": 35_000_000,
            "Library/Hard_Bounce/Stray.aiff": 10}
    for rel, size in held.items():
        file = paths.root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"x" * size)
    return [{"path": str(paths.root / rel), "artist": artist, "Title": title} for rel, artist, title in (
        (LOSSLESS, "Vatoz Locoz", "Gimme Gimme"), ("Library/Hard_Bounce/Gone.aiff", "Some Artist", "Gone Track"),
        ("Superseded/Hard_Bounce/Old.mp3", "Armin Hermann", "Get Naughty (old)"),
        ("Library/Hard_Bounce/Stray.aiff", "Stray Artist", "Stray Title"))]


@pytest.fixture
def fixture(tmp_path, monkeypatch, request, utc):
    """The hub fixtures every read runs on: a library of three songs, a rekordbox library with no tracks, rekordbox
    closed (conftest). The reads of To-do and one track run on `rich_library` (an upgrade waiting, two open checks), `missing list` on
    `missing_library` (five songs whose file is missing)."""
    entry = request.node.callspec.params.get("entry") if hasattr(request.node, "callspec") else None
    if entry is not None and entry.command in RICH:
        return rich_library(tmp_path, monkeypatch).root
    if entry is not None and entry.command == ("missing", "list"):
        return missing_library(tmp_path, monkeypatch).root
    if entry is not None and entry.command in STUBBED:
        stub_headless(monkeypatch, "1.0.0")  # the pages never show this Mac's browsers or tools, nor the version of the day
    if entry is not None and entry.command in TIMED:
        with_clock(monkeypatch)
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    if entry is not None and (entry.command[0] == "batch" or entry.command == ("history",)):
        with_batches(paths)  # two AIFF batches and a move batch: the typed ids `aiff:1`, `aiff:2`, `moves:1`
    if entry is not None and entry.command in DOCTORS:
        with_doctor(paths)
    if entry is not None and entry.command == ("sync", "plan"):
        with_read(paths, monkeypatch)
    if entry is not None and entry.command in (("report", "show"), ("report", "list"), ("history",)):
        with_report(paths)
    if entry is not None and entry.command == ("open", "report"):
        (paths.reports / f"{with_report(paths)}.md").write_text("# Run\n")  # `open report` opens the written page, not the data
    if entry is not None and entry.command == ("open", "licences"):
        (tmp_path / "licenses").mkdir()  # the checkout's own folder is no place for a golden
        monkeypatch.setattr(tools, "licenses_dir", lambda: tmp_path / "licenses")
    make_master(tmp_path / "rekordbox", with_match(paths) if entry is not None and entry.command in MATCHES else [])
    os.utime(tmp_path / "rekordbox" / "master.db", (MASTER_TIME, MASTER_TIME))
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox"))
    if entry is not None and entry.command == ("rekordbox", "backups"):
        with_backups(tmp_path, monkeypatch)
    shutil.copyfile(CLICKS, tmp_path / LOSSY)  # a real file where the fake one was: `rekordbox preview` decodes it
    return tmp_path


def check_golden(name: str, text: str) -> None:
    """The one golden compare: `text` equals `tests/cli_golden/<name>.txt` (`UPDATE_GOLDEN=1` writes it). A write's page
    is checked here too, by the test that runs the write (`WRITES` names its file)."""
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text)
    assert path.exists(), f"no golden text for {name}: run with UPDATE_GOLDEN=1 and read it"
    assert text == path.read_text()


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def words(entry, root: Path) -> list[str]:
    """The command line of a read's example. `setup music`'s names a folder under `root` that does not exist yet: the
    catalogue's `/Music/Discjockey` is "not writable" only where `/` is not writable (a page must not depend on the machine)."""
    line = shlex.split(entry.example)
    if entry.command == ("setup", "music"):
        line = [str(root / "Elsewhere" / "Discjockey") if word == "/Music/Discjockey" else word for word in line]
    return line


def golden_page(argv: list[str], root: Path, capsys, *, also: tuple = ()) -> tuple[int, str, str, dict]:
    """The page of a command as its golden keeps it, and the notices that went with it: the line runs with `--json`, `root`
    (and every regex in `also`) is replaced by a fixed word in that text, and the page is printed from the scrubbed
    answer. The printer pads its columns to the longest cell, so scrubbing the finished page (the old way) made the
    golden depend on how long the temp folder's name was. Returns (exit code, page, notices as stderr holds them, the
    scrubbed envelope)."""
    code, out, _ = run([*argv, "--json"], capsys)
    notices = "\n".join(cli.notices(cli.runnable(json.loads(out))))
    out = out.replace(json.dumps(str(root))[1:-1], "<tmp>")
    for pattern, word in also:
        out = re.sub(pattern, word, out)
    env = json.loads(out)
    text = cli.render_text(env, parser.parse(argv).flags)
    return code, text + "\n" if text else "", notices, env


SPECTRUM_DATA = re.compile(r"(?m)^(Data\s+)[A-Za-z0-9+/=]{100,}$")  # the base64 of the picture: it depends on the ffmpeg build


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_golden_text(entry, fixture, capsys):
    skip_without_tools(entry)
    argv = words(entry, fixture)
    code, page, notices, env = golden_page(argv, fixture, capsys, also=((r"plan:[0-9a-f]{12}", "plan:<id>"),))  # a plan's id is a hash of the music folder's path: a different one on every run
    _, _, err = run(argv, capsys)  # the line as typed: its stderr holds what to run next
    assert code == 0 and all(line.startswith("Next: ") for line in err.splitlines())  # what to run next is a notice, not a page
    if entry.command == ("track", "spectrum"):
        shown = env["data"]["spectrum"]
        size = shown["cols"] * shown["bands"]
        assert len(base64.b64decode(shown["data"])) == size
        assert SPECTRUM_DATA.search(page), "the picture's base64 is on the page"
        page = SPECTRUM_DATA.sub(rf"\g<1><base64, {size} bytes>", page)
    check_golden(golden_name(entry), page)


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_t7_prime_every_leaf_of_data_is_in_the_verbose_text(entry, fixture, capsys):
    skip_without_tools(entry)
    _, out, _ = run([*words(entry, fixture), "--json"], capsys)
    data = json.loads(out)["data"]
    code, text, _ = run([*words(entry, fixture), "--verbose", "--limit", "0"], capsys)
    assert code == 0
    missing = dropped(data, text)
    assert not missing, f"{entry.command}: {missing[:5]} are not in the text"


def dropped(data, text: str) -> list[str]:
    """The leaves of `data` the text does not print as often as `data` holds them. A leaf counts as a whole word: `no`
    in "nothing", `1` in "12" and a relative path inside an absolute one are not it (a substring test passed a page
    that dropped every boolean, null and small number)."""
    out = []
    for leaf, n in Counter(generic.leaves(data)).items():
        if len(re.findall(rf"(?<![\w.:/-]){re.escape(leaf)}(?![\w.:/-])", text)) < n:
            out.append(leaf)
    return out


def test_dropped_finds_a_boolean_a_null_and_a_small_number_a_substring_would_find():
    text = "12 of 340 shown · nonetheless nothing here"
    data = {"a": False, "b": None, "n": 1}
    assert [leaf for leaf in generic.leaves(data) if leaf not in text] == []  # the old substring test found all three
    assert dropped(data, text) == ["no", "none", "1"]
    assert dropped(data, "a: no, b: none, n: 1 · 12 of 340 shown") == []
    assert dropped({"a": True, "b": True}, "yes") == ["yes"]  # two of them, one printed
    assert dropped({"p": "a/b.mp3"}, "in /music/a/b.mp3") == ["a/b.mp3"]  # a relative path is not the end of an absolute one


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_t4_json_data_is_the_bridge_answer_minus_ok(entry, fixture, capsys):
    skip_without_tools(entry)
    parsed = parser.parse(words(entry, fixture))
    api = bind.default()
    kwargs, failed = call._arguments(entry, parsed.args, " ".join(entry.command), api, exact=False)  # what `call.run` makes of the line
    assert failed is None, failed
    answer = getattr(api, entry.method)(**kwargs)
    assert answer["ok"], answer
    _, out, _ = run([*words(entry, fixture), "--json"], capsys)
    # an answer that says what to run next (a search with no hit) has it in the envelope's `next`, and the live steps of a
    # running job (`status`) in its `person_steps`, not in `data`;
    # a headless api has no media server, so no answer carries a hub URL
    assert json.loads(out)["data"] == {k: v for k, v in answer.items() if k not in ("ok", "next", "person_steps")}


def test_every_built_read_has_a_golden_file_and_no_golden_file_is_left_over():
    wanted = {f"{golden_name(e)}.txt" for e in READS} | {f"{name}.txt" for name in WRITES}
    assert {p.name for p in GOLDEN.glob("*.txt")} == wanted


def test_no_read_has_the_golden_file_of_a_write():
    assert not [e.method for e in READS if golden_name(e) in WRITES]


def test_a_list_of_sentences_is_joined_by_a_space_and_any_other_list_by_a_comma():
    assert generic.cell(["First one.", "Second one!", "Third one?"]) == "First one. Second one! Third one?"
    assert generic.cell(["First one.", "no stop"]) == "First one., no stop"  # one that is not a sentence: a plain list
    assert generic.cell(["a", "b"]) == "a, b" and generic.cell([1, 2]) == "1, 2" and generic.cell([]) == "none"
    assert generic.cell([["One.", "Two."], ["Three."]]) == "One. Two., Three."  # a list of lists: each is a sentence list
