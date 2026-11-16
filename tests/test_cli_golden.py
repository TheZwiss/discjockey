"""The golden and parity harnesses (issue 39, plan v2 §3.1): one parametrised test per built read entry of the
catalogue. A group that builds a read gives its entry an `example` (the command line to run on the fixture) and gets
all three for free:

* golden: the text page equals `tests/cli_golden/<noun>_<verb>.txt` (`UPDATE_GOLDEN=1` writes it; a reviewer reads the
  diff to see the page);
* T7': every leaf of `data`, as the printer writes it, occurs in the text with `--verbose` (pages may reorder and
  word, never drop);
* T4: `--json`'s `data` equals the bridge's answer minus `ok` (and `next`, which the envelope carries)."""
import json
import os
import re
import shlex
import shutil
import time
from collections import Counter
from pathlib import Path

import pytest
from hub_helpers import LOSSY, choose_music, make_root
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import library
from test_cli_batches import with_batches, with_report
from test_cli_reads import rich_library
from discjockey.cli import bind, parser
from discjockey.cli.render import generic
from discjockey.hub import catalog

GOLDEN = Path(__file__).parent / "cli_golden"
READS = [e for e in parser.built() if e.kind == "R"]
WRITES = ["library_facts", "aiff_convert", "aiff_rename", "upgrade_apply", "upgrade_discard", "track_undo", "check_done", "batch_resume", "batch_undo", "rekordbox_restore", "sync_run", "folder_add", "folder_remove", "settings_set"]  # the writes with a golden page (their own tests run them: tests/test_cli_upgrade.py)


RICH = {("todo", "list"), ("upgrade", "list"), ("check", "list"), ("track", "show")}  # reads that need a better version
                                                                                        # parked and checks open
CLICKS = Path(__file__).parent / "fixtures" / "clicks-lame.mp3"  # the one real audio file: a preview decodes it


def skip_without_tools(entry):
    """`rekordbox preview` decodes a real file: without ffmpeg and ffprobe it skips, like the other audio tests."""
    if entry.method == "rekordbox_preview" and (shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None):
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


@pytest.fixture
def fixture(tmp_path, monkeypatch, request, utc):
    """The hub fixtures every read runs on: a library of three songs, a rekordbox library with no tracks, rekordbox
    closed (conftest). The reads of To-do and one track run on `rich_library` (an upgrade waiting, two open checks)."""
    entry = request.node.callspec.params.get("entry") if hasattr(request.node, "callspec") else None
    if entry is not None and entry.command in RICH:
        return rich_library(tmp_path, monkeypatch).root
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    if entry is not None and entry.command[0] == "batch":
        with_batches(paths)  # two AIFF batches and a move batch: the typed ids `aiff:1`, `aiff:2`, `moves:1`
    if entry is not None and entry.command == ("report", "show"):
        with_report(paths)
    make_master(tmp_path / "rekordbox", [])
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


def words(entry) -> list[str]:
    return shlex.split(entry.example)


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_golden_text(entry, fixture, capsys):
    skip_without_tools(entry)
    code, out, err = run(words(entry), capsys)
    assert code == 0 and err == ""
    check_golden("_".join(entry.command), out.replace(str(fixture), "<tmp>"))


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_t7_prime_every_leaf_of_data_is_in_the_verbose_text(entry, fixture, capsys):
    skip_without_tools(entry)
    _, out, _ = run([*words(entry), "--json"], capsys)
    data = json.loads(out)["data"]
    code, text, _ = run([*words(entry), "--verbose", "--limit", "0"], capsys)
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
    parsed = parser.parse(words(entry))
    api = bind.default()
    kwargs = dict(parsed.args)
    for name, arg in catalog.effective_params(entry, parser.signature_of(entry.method)).items():
        if arg.resolve and name in kwargs:
            resolved = api.resolve(arg.resolve, list(kwargs[name]) if arg.many else [kwargs[name]])["resolved"]
            kwargs[name] = resolved if arg.many else resolved[0]
    answer = getattr(api, entry.method)(**kwargs, **entry.fixed)
    assert answer["ok"], answer
    _, out, _ = run([*words(entry), "--json"], capsys)
    # an answer that says what to run next (a search with no hit) has it in the envelope's `next`, not in `data`;
    # a headless api has no media server, so no answer carries a hub URL
    assert json.loads(out)["data"] == {k: v for k, v in answer.items() if k not in ("ok", "next")}


def test_every_built_read_has_a_golden_file_and_no_golden_file_is_left_over():
    wanted = {f"{'_'.join(e.command)}.txt" for e in READS} | {f"{name}.txt" for name in WRITES}
    assert {p.name for p in GOLDEN.glob("*.txt")} == wanted
