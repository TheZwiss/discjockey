"""Group V4.1a (issue 39, design §5.2, §7.1): `sync read` and `sync run`, the whole sync, through the command line on a
fixture library and a fixture rekordbox (`batch_helpers.make_lib`), the playlists read by stubs (no network).

The jobs run in this process (`test_cli_upgrade.inline_workers`: the same worker, spawn and registry). The sync's
Auto-upgrade phase alone is `test_cli_sync_phase.py`; the engine rules of `start_sync` are `test_hub_api_write.py`."""
from __future__ import annotations

import json

import pytest
from hub_helpers import cmd, fake_spotify

from batch_helpers import needs_ffmpeg
from discjockey import library
from discjockey import words
from discjockey.hub import api as api_mod
from discjockey.hub import registry
from discjockey.models import SourceTrack
from discjockey.settings import Settings, save_settings
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


def test_a_finished_sync_read_says_how_fresh_the_read_and_the_scan_are(synced, capsys):
    synced(["mp3", "aiff"])
    code, env = run_json(["sync", "read"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert env["as_of"]["read_at"] and env["as_of"]["scanned_at"], env["as_of"]  # as every read's envelope does
    assert env["as_of"] == run_json(["sync", "plan"], capsys)[1]["as_of"]  # from the same stored records


def test_sync_read_without_playlists_to_read_is_refused_not_set_up_and_holds_no_lock(synced, capsys):
    found = synced(["mp3", "aiff"])
    found.paths.playlists_file.unlink()
    code, env = run_json(["sync", "read"], capsys)
    assert (code, env["outcome"], env["reason"]) == (7, "refused", "not_set_up"), env
    assert [s["library_lock"] for s in job_states(found)] == [False]


# --- sync run ---

def test_sync_run_reads_nothing_and_runs_nothing_without_a_read(synced, capsys):
    found = synced(["mp3", "aiff"])
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"], env["reason"], env["message"]) == (7, "refused", "not_set_up", words.SYNC_NEEDS_READ)
    assert env["next"][0]["run"].endswith("sync read")
    code, dry = run_json(["sync", "run", "--dry-run"], capsys)  # the dry run is `sync plan`'s answer: it says nothing was read
    assert code == OK and dry["data"] == run_json(["sync", "plan"], capsys)[1]["data"] and dry["data"]["plan_id"] is None
    assert not found.paths.support.joinpath("plans").exists()
    assert not job_states(found)  # a refused run starts no job; no read ran


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


def test_a_whole_sync_whose_phase_upgraded_songs_says_its_batch_and_the_steps_for_rekordbox(synced, capsys):
    """The phase's words are the phase alone's (`sync run --auto-upgrade-only`, test_cli_sync_phase): its batch in `data`,
    what to run next and the steps only a person can do in rekordbox."""
    found = synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert env["data"]["counts"]["upgraded"] == 2 and env["data"]["batch_id"] == f"aiff:{batches_of(found)[0].id}"
    assert [n["run"] for n in env["next"]] == [cmd(f"batch show {env['data']['batch_id']}"), cmd("check list")]
    assert env["person_steps"] and all(s["id"].startswith("step:") for s in env["person_steps"]), env["person_steps"]


def test_a_whole_sync_whose_phase_did_nothing_carries_no_batch_and_no_steps(synced, capsys):
    found = synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    save_settings(found.paths.settings_file, Settings(auto_upgrade=False))  # the phase moves nothing
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert "batch_id" not in env["data"] and env["next"] == [] and env["person_steps"] == [] and not batches_of(found), env


# --- what a failed whole sync answers ---

def written_report(paths, *sections, exit_code=0):
    """A sync whose work ended at once, leaving a real report with a result in each of `sections`."""
    from datetime import datetime

    from discjockey import report
    from discjockey.events import Result
    log = report.RunLog(datetime(2026, 11, 23, 9, 0))
    for i, section in enumerate(sections):
        log.add(Result(section, "A", f"Artist {i}", f"Title {i}", f"t{i}", "went wrong" if section == "errors" else ""))
    path = report.write_run(paths, log, datetime(2026, 11, 23, 9, 5), exit_code)
    return {"exit_code": exit_code, "report": str(path), "actions": len(sections), "new_since_plan": []}


@pytest.mark.parametrize("sections, exit_code, outcome, code", [
    (("new_lossless", "errors"), 1, "partial", 6), (("errors",), 1, "failed", 1), (("new_lossless",), 0, "ok", 0)])
def test_a_sync_that_failed_songs_is_partial_or_failed_with_what_failed(synced, monkeypatch, capsys, sections, exit_code,
                                                                       outcome, code):
    found = synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    monkeypatch.setattr(api_mod, "sync_work", lambda paths, *rest, **kw: (
        lambda ctx: written_report(paths, *sections, exit_code=exit_code)))
    got, env = run_json(["sync", "run"], capsys)
    assert (got, env["outcome"]) == (code, outcome), env
    assert env["data"]["counts"] == {s: 1 for s in sections}
    assert [f["text"] for f in env["data"]["failed"]] == (["went wrong"] if "errors" in sections else [])


def test_a_sync_whose_report_cannot_be_read_and_exit_code_is_1_is_failed(synced, monkeypatch, capsys):
    synced(["mp3", "aiff"])
    assert run_json(["sync", "read"], capsys)[0] == OK
    monkeypatch.setattr(api_mod, "sync_work", lambda paths, *rest, **kw: (
        lambda ctx: {"exit_code": 1, "report": str(paths.reports / "gone.md"), "actions": 0, "new_since_plan": []}))
    code, env = run_json(["sync", "run"], capsys)
    assert (code, env["outcome"]) == (1, "failed"), env


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

def plan_files(found) -> list[str]:
    return sorted(p.name for p in found.paths.support.joinpath("plans").glob("*")) if found.paths.support.joinpath("plans").exists() else []


@pytest.fixture
def spawned(monkeypatch):
    """The workers the command line starts (it is `inline_workers`' spawn, counted)."""
    from discjockey.cli import call
    started = []
    real = call.spawn_worker
    monkeypatch.setattr(call, "spawn_worker", lambda *a, **k: (started.append(a), real(*a, **k))[1])
    return started


def test_every_refusal_the_engine_decides_for_sync_run_is_answered_before_any_job_starts(two_to_download, stubbed_sync,
                                                                                         spawned, capsys):
    """A refused write changes nothing: no worker, no job record or folder, no plan file (the window's refusal starts no
    job either). The words, outcome and exit code are the engine's own."""
    found = two_to_download()
    unknown = "plan:000000000000"
    refusals = [  # (line, exit, outcome, reason, words)
        (["sync", "run"], 7, "refused", "not_set_up", words.SYNC_NEEDS_READ),  # nothing read yet
        (["sync", "run", "act:x"], 2, "bad_args", "usage", words.SYNC_IDS_NEED_PLAN),
        (["sync", "run", "--how-many", "many"], 2, "bad_args", "usage", words.BAD_HOW_MANY),
        (["sync", "run", "--plan", unknown], 2, "bad_args", "unknown_id", None),
        (["sync", "run", "act:x", "--how-many", "5", "--plan", unknown], 2, "bad_args", "conflicting_flags",
         words.SYNC_IDS_OR_HOW_MANY),
    ]

    def check_all():
        for line, exit_code, outcome, reason, text in refusals:
            code, env = run_json(line, capsys)
            assert (code, env["outcome"], env["reason"]) == (exit_code, outcome, reason), (line, env)
            assert env["job"] is None and (text is None and unknown in env["message"] or env["message"] == text), (line, env)
            assert not job_states(found) and not spawned and not list(found.paths.support.joinpath("jobs").glob("*")), line
            assert plan_files(found) == [], line
    check_all()
    assert run_json(["sync", "run"], capsys)[1]["next"][0]["run"].endswith("sync read")
    assert run_json(["sync", "read"], capsys)[0] == OK
    spawned.clear()
    plan_id, ids = plan_of(run_json(["sync", "run", "--dry-run"], capsys)[1])
    stored = plan_files(found)
    for line, outcome in ((["sync", "run", "act:nope", "--plan", plan_id], "refused"),  # an id the plan has not
                          (["sync", "run", "--plan", unknown], "bad_args")):
        code, env = run_json(line, capsys)
        assert env["outcome"] == outcome and code != OK, (line, env)
        assert env["job"] is None and len(spawned) == 0, line
    assert plan_files(found) == stored
    assert [s["method"] for s in job_states(found)] == ["refresh"]  # the read's job, and no other


def test_a_check_before_a_job_belongs_to_a_write_job_method_of_the_catalogue():
    """`call._prejob` finds `prejob_<method>` on the api: each one is the check of a J / RJ entry's method."""
    from discjockey.hub import catalog
    checks = [n[len("prejob_"):] for n in dir(api_mod.CliApi) if n.startswith("prejob_") and callable(getattr(api_mod.CliApi, n))]
    assert checks
    for method in checks:
        assert any(e.kind in ("J", "RJ") for e in catalog.by_method(method)), method


def test_a_sync_run_that_passes_the_check_starts_its_job_once(two_to_download, stubbed_sync, spawned, capsys):
    found = two_to_download()
    assert run_json(["sync", "read"], capsys)[0] == OK
    spawned.clear()
    code, env = run_json(["sync", "run", "--how-many", "1"], capsys)
    assert (code, env["outcome"]) == (OK, "ok") and len(spawned) == 1 and len(sync_states(found)) == 1, env


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

