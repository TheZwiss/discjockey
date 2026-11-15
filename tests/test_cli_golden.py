"""The golden and parity harnesses (issue 39, plan v2 §3.1): one parametrised test per built read entry of the
catalogue. A group that builds a read gives its entry an `example` (the command line to run on the fixture) and gets
all three for free:

* golden: the text page equals `tests/cli_golden/<noun>_<verb>.txt` (`UPDATE_GOLDEN=1` writes it; a reviewer reads the
  diff to see the page);
* T7': every leaf of `data`, as the printer writes it, occurs in the text with `--verbose` (pages may reorder and
  word, never drop);
* T4: `--json`'s `data` equals the bridge's answer minus `ok`."""
import json
import os
import shlex
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey.cli import bind, parser
from discjockey.cli.render import generic
from discjockey.hub import catalog

GOLDEN = Path(__file__).parent / "cli_golden"
READS = [e for e in parser.built() if e.kind == "R"]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """The hub fixtures every read runs on: a library of three songs, a rekordbox library with no tracks, rekordbox
    closed (conftest)."""
    make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    make_master(tmp_path / "rekordbox", [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox"))
    return tmp_path


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def words(entry) -> list[str]:
    return shlex.split(entry.example)


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_golden_text(entry, fixture, capsys):
    code, out, err = run(words(entry), capsys)
    assert code == 0 and err == ""
    text = out.replace(str(fixture), "<tmp>")
    path = GOLDEN / f"{'_'.join(entry.command)}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text)
    assert path.exists(), f"no golden text for {entry.command}: run with UPDATE_GOLDEN=1 and read it"
    assert text == path.read_text()


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_t7_prime_every_leaf_of_data_is_in_the_verbose_text(entry, fixture, capsys):
    _, out, _ = run([*words(entry), "--json"], capsys)
    data = json.loads(out)["data"]
    code, text, _ = run([*words(entry), "--verbose", "--limit", "0"], capsys)
    assert code == 0
    missing = [leaf for leaf in generic.leaves(data) if leaf not in text]
    assert not missing, f"{entry.command}: {missing[:5]} are not in the text"


@pytest.mark.parametrize("entry", READS, ids=lambda e: "_".join(e.command))
def test_t4_json_data_is_the_bridge_answer_minus_ok(entry, fixture, capsys):
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
    assert json.loads(out)["data"] == {k: v for k, v in answer.items() if k != "ok"}


def test_every_built_read_has_a_golden_file_and_no_golden_file_is_left_over():
    wanted = {f"{'_'.join(e.command)}.txt" for e in READS}
    assert {p.name for p in GOLDEN.glob("*.txt")} == wanted
