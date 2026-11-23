"""Group V4.1a (issue 39, design §5.2, §7.1): `sync read` and `sync run`, the whole sync, through the command line on a
fixture library and a fixture rekordbox (`batch_helpers.make_lib`), the playlists read by stubs (no network).

The jobs run in this process (`test_cli_upgrade.inline_workers`: the same worker, spawn and registry). The sync's
Auto-upgrade phase alone is `test_cli_sync_phase.py`; the engine rules of `start_sync` are `test_hub_api_write.py`."""
from __future__ import annotations

import json

import pytest
from hub_helpers import fake_spotify

from batch_helpers import needs_ffmpeg
from discjockey import library
from discjockey import words
from discjockey.hub import api as api_mod
from discjockey.hub import registry
from discjockey.models import SourceTrack
from test_cli_upgrade import STOP, batches_of, inline_workers, lib, run, run_json  # noqa: F401 - fixtures

pytestmark = needs_ffmpeg

OK = 0
PLAYLIST_ID = "0DiscjockeyExampleList"


@pytest.fixture
def synced(lib, monkeypatch):
    """A library whose one playlist (the lib's folder `A`) holds exactly its songs: its plan has no action, so a sync runs
    the Auto-upgrade phase alone. `sync read` is not run yet."""
    def build(kinds):
        found = lib(kinds)
        fake_spotify(monkeypatch, {PLAYLIST_ID: [SourceTrack(t, f"Song {i}", ("Artist",), "Album", None, 30000, None)
                                                 for i, t in enumerate(found.tracks)]})
        found.paths.playlists_file.write_text(f"A = https://open.spotify.com/playlist/{PLAYLIST_ID}\n")
        return found
    return build


def job_states(found) -> list[dict]:
    return registry.Registry(found.paths.support).list(all=True)


def sync_states(found) -> list[dict]:
    return [s for s in job_states(found) if s.get("method") == "start_sync"]


@pytest.fixture
def stubbed_sync(monkeypatch):
    """A sync's job ends at once and records the plan and the ids it would run (`sync_work`), so a plan with downloads
    in it asks Qobuz for nothing."""
    runs = []

    def fake_sync_work(paths, planned, chosen, *rest, **kw):
        runs.append((dict(planned), list(chosen)))
        return lambda ctx: {"exit_code": 0, "report": str(paths.reports / "x.md"), "actions": len(chosen), "new_since_plan": []}
    monkeypatch.setattr(api_mod, "sync_work", fake_sync_work)
    return runs


@pytest.fixture
def two_to_download(synced, monkeypatch):
    """The playlist holds the library's songs and two the library lacks: the plan has two downloads."""
    def build():
        found = synced(["mp3", "aiff"])
        songs = [SourceTrack(t, f"Song {i}", ("Artist",), "Album", None, 30000, None) for i, t in enumerate(found.tracks)]
        songs += [SourceTrack(f"newsong{i}", f"New {i}", ("Someone",), "Album", None, 180000, None) for i in range(2)]
        fake_spotify(monkeypatch, {PLAYLIST_ID: songs})
        return found
    return build


def plan_of(env: dict) -> tuple[str, list[str]]:
    """The plan id and the action ids a `sync plan` / `sync run --dry-run` answer shows, in run order."""
    data = env["data"]
    return data["plan_id"], [a["id"] for g in data["groups"] for a in g["actions"]]


# --- sync read ---

def test_sync_read_reads_the_playlists_in_a_worker_and_stores_the_read(synced, capsys):
    found = synced(["mp3", "aiff"])
    code, env = run_json(["sync", "read"], capsys)
    assert (code, env["outcome"], env["data"]["read_id"], env["data"]["actions"]) == (OK, "ok", "read:1", 0), env
    [state] = job_states(found)
    assert state["method"] == "refresh" and state["status"] == "done" and state["library_lock"] is False
    assert run_json(["sync", "plan"], capsys)[1]["data"]["read_id"] == "read:1"  # the plan comes from this read


def test_sync_read_says_in_the_registry_that_it_holds_the_library_only_while_its_scan_does(synced, monkeypatch, capsys):
    found = synced(["mp3", "aiff"])
    seen = []
    real_scan = library.scan_library

    def scan_that_looks(*args, **kwargs):
        seen.append([s["library_lock"] for s in job_states(found) if s.get("method") == "refresh"])
        return real_scan(*args, **kwargs)
    monkeypatch.setattr(library, "scan_library", scan_that_looks)
    assert run_json(["sync", "read"], capsys)[0] == OK
    assert seen == [[True]]  # its scan held the lock and the record said so (other processes name the holder)
    assert [s["library_lock"] for s in job_states(found)] == [False]  # and let go of it again


# --- sync run ---

def test_sync_run_reads_nothing_and_runs_nothing_without_a_read(synced, capsys):
    found = synced(["mp3", "aiff"])
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"], env["reason"], env["message"]) == (7, "refused", "not_set_up", words.SYNC_NEEDS_READ)
    assert env["next"][0]["run"].endswith("sync read")
    code, dry = run_json(["sync", "run", "--dry-run"], capsys)  # the dry run is `sync plan`'s answer: it says nothing was read
    assert code == OK and dry["data"] == run_json(["sync", "plan"], capsys)[1]["data"] and dry["data"]["plan_id"] is None
    assert not found.paths.support.joinpath("plans").exists()
    assert [s["method"] for s in job_states(found)] == ["start_sync"]  # the refused run's job; no read ran


def test_sync_run_runs_the_last_phase_when_the_plan_has_no_action_and_counts_what_it_did(synced, capsys):
    found = synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert env["data"]["counts"]["upgraded"] == 2 and env["data"]["failed"] == [] and env["data"]["actions"] == 0
    assert len(batches_of(found)) == 1  # the Auto-upgrade phase made its batch
    [state] = sync_states(found)
    assert state["args"]["selected"] == [] and state["args"]["plan_id"].startswith("plan:")


def test_sync_run_dry_run_is_the_sync_plan_and_writes_only_its_plan(two_to_download, capsys):
    found = two_to_download()
    assert run_json(["sync", "read"], capsys)[0] == OK
    _, shown = run_json(["sync", "plan"], capsys)
    before = sorted(p.name for p in found.paths.support.rglob("*") if p.is_file() and "plans" not in p.parts)
    code, dry = run_json(["sync", "run", "--dry-run"], capsys)
    assert code == OK and dry["data"] == shown["data"] and len(plan_of(dry)[1]) == 2
    assert dry["command"] == "sync run" and not sync_states(found)
    assert sorted(p.name for p in found.paths.support.rglob("*") if p.is_file() and "plans" not in p.parts) == before


def test_sync_run_how_many_runs_the_first_downloads_and_records_what_it_runs(two_to_download, stubbed_sync, capsys):
    found = two_to_download()
    assert run_json(["sync", "read"], capsys)[0] == OK
    plan_id, ids = plan_of(run_json(["sync", "run", "--dry-run"], capsys)[1])
    code, env = run_json(["sync", "run", "--how-many", "1"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert stubbed_sync[-1][1] == ids[:1]
    [state] = sync_states(found)  # what runs, not the words of the line: the Sync page shows these ticks
    assert state["args"] == {"plan_id": plan_id, "selected": ids[:1], "how_many": "1"}


def test_sync_run_with_action_ids_runs_those_of_the_plan_it_names(two_to_download, stubbed_sync, capsys):
    found = two_to_download()
    assert run_json(["sync", "read"], capsys)[0] == OK
    plan_id, ids = plan_of(run_json(["sync", "run", "--dry-run"], capsys)[1])
    code, env = run_json(["sync", "run", ids[1], "--plan", plan_id], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert stubbed_sync[-1][1] == [ids[1]]
    assert sync_states(found)[0]["args"] == {"plan_id": plan_id, "selected": [ids[1]]}
    code, env = run_json(["sync", "run", ids[1]], capsys)  # ids belong to a plan: say which
    assert (code, env["outcome"], env["reason"], env["message"]) == (2, "bad_args", "usage", words.SYNC_IDS_NEED_PLAN)
    code, env = run_json(["sync", "run", ids[1], "--plan", plan_id, "--how-many", "1"], capsys)
    assert (code, env["reason"], env["message"]) == (2, "conflicting_flags", words.SYNC_IDS_OR_HOW_MANY)
    code, env = run_json(["sync", "run", "--how-many", "many"], capsys)
    assert (code, env["reason"], env["message"]) == (2, "usage", words.BAD_HOW_MANY)


# --- the page ---

def test_golden_the_page_of_a_sync_run(synced, capsys, tmp_path):
    import re

    from test_cli_golden import WRITES, check_golden
    synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    code, out, err = run(["sync", "run"], capsys)
    assert code == OK and "sync_run" in WRITES
    text = out.replace(str(tmp_path), "<tmp>")
    text = re.sub(r"reports/\d{4}-\d{2}-\d{2}_\d{6}\.md", "reports/<stamp>.md", text)  # the clock of the run
    check_golden("sync_run", text)


# --- what the console's sync (deleted in V4.1b) pinned that no other test did ---

def test_sync_read_with_a_playlists_file_that_cannot_be_read_is_config_invalid_and_stores_nothing(synced, capsys):
    found = synced(["mp3", "aiff"])
    found.paths.playlists_file.write_text("Bouncy =\n")
    code, env = run_json(["sync", "read"], capsys)
    assert (code, env["outcome"], env["reason"]) == (1, "failed", "config_invalid") and "line 1" in env["message"], env
    assert run_json(["sync", "plan"], capsys)[1]["data"]["read_id"] is None


def test_sync_read_and_sync_run_are_busy_while_another_run_holds_the_library(synced, capsys):
    found = synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    with library.run_lock(found.paths.lock):
        for line in (["sync", "read"], ["sync", "run"]):
            code, env = run_json(line, capsys)
            assert (code, env["outcome"]) == (3, "busy"), (line, env)


def test_sync_read_of_a_spotify_playlist_without_a_spotify_login_says_to_set_it_up(synced, monkeypatch, capsys):
    from discjockey.sources import spotify

    def no_session(paths):
        raise spotify.SpotifyError("Spotify is not set up yet. Run: discjockey setup")
    synced(["mp3", "aiff"])
    monkeypatch.setattr(spotify, "load_session", no_session)
    code, env = run_json(["sync", "read"], capsys)
    assert code != OK and env["outcome"] == "failed" and "Spotify is not set up yet" in env["message"], env


def test_sync_read_of_a_qobuz_only_playlists_file_never_asks_for_spotify(synced, monkeypatch, capsys):
    from hub_helpers import QOBUZ_LINK, fake_qobuz, qobuz_track
    from discjockey.sources import spotify

    found = synced(["mp3", "aiff"])
    found.paths.playlists_file.write_text(f"Example_Playlist = {QOBUZ_LINK}\n")
    fake_qobuz(monkeypatch, [qobuz_track("900100001", "Example Song", "Example Artist")])
    monkeypatch.setattr(spotify, "load_session", lambda paths: pytest.fail("Spotify was not asked for"))
    code, env = run_json(["sync", "read"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert [a["reason"] for g in run_json(["sync", "plan"], capsys)[1]["data"]["groups"] for a in g["actions"]] == ["new"]

