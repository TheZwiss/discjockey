"""Rehearse issue 43's missing files end to end, with the command line, on made-up data (plan 2026-11-17-missing-files-plan
§10.2, group D1).

Nothing here touches the real library, the real rekordbox or the network. Every file is made up (click tracks from
`scripts/make_upgrade_test.py`); the work folder must be new or empty and lie outside the repo; every Discjockey command
and every helper process runs with `DISCJOCKEY_SUPPORT=W/support` and `DISCJOCKEY_REKORDBOX=W/rb` (an empty folder), both
printed first and checked for each child process; each command runs with every proxy pointing at a closed port.

    uv run python scripts/missing_files_rehearsal.py --work W        # W: a new folder outside the repo

The steps (each runs `bin/discjockey ... --json` and checks the answer):
 1. Setup: music folder `W/music`, an import folder `W/crate` with a click MP3 (`folder add`, its import),
    `--attach-upgrades` (a parked upgrade); `track show` gives the song's key K, the upgrade parked.
 2. Own song: the file moves to `W/away/`; `library scan` -> missing 1; `missing list` -> one item, action remove;
    `track show K` -> missing since set, upgrade parked.
 3. Back: the file moves to `W/crate/sub/renamed.mp3`; `library scan` -> back 1; `track show K` -> the same key, the new
    path, upgrade parked; nothing waits to import; `missing list` empty.
 4. Playlist song (Download again): a second click file as a playlist song's file in `W/music/Library/Rehearsal/`; the
    file moves out; the scan; the plan holds no acquire; `missing download --dry-run`, `missing download`; the plan
    holds `acquire` `redownload`; the file comes back; the scan -> back 1; no acquire, `file_gone` cleared.
 5. Remove: K's file moves out again; scan; `missing remove K --dry-run`; without `--yes` it is refused and nothing
    changes; with `--yes` the song and its parked file go, the file in `W/away/` is untouched.
 6. Placement (D9): a third click file as a playlist song's file in `W/music/Library/Rehearsal/not_lossless/` with a
    parked upgrade, the switch off; the file moves out; Download again leaves the song to the sync's last phase;
    `sync run --auto-upgrade-only` puts the parked version in; `track undo` makes the song missing again.

`sync plan` is not built in the command line (its planned phase), so the plan of steps 4 and 6 is made by
`planner.plan` on a playlist made up here from the stored songs; `folder list` is not built either, so "nothing waits
to import" is read from the scratch library.db (read-only). Steps that need the network or a running rekordbox report
SKIP with the reason. Prints one PASS/FAIL/SKIP line per check, writes `W/report.json`; exit 0 when no check fails, 1
otherwise, 2 when it refuses to run (as `rekordbox_rehearsal.py`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from discjockey import audio, library, planner, upgrades  # noqa: E402
from discjockey.library import Paths  # noqa: E402
from discjockey.models import FetchedPlaylist, PlaylistLine, SourceTrack  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402
from discjockey.rekordbox import process  # noqa: E402

FOLDER = "Rehearsal"
PARKED_DIR = "Upgrades ready/_Upgrade test"
SONG_4 = "4RehearsalPlaylistSong"  # a Spotify-shaped key (22 letters and digits): the commands take it as a song
SONG_6 = "6RehearsalPlaylistSong"
REFUSED = 7  # the exit code of a refusal (`discjockey help`'s exit codes)
DEAD_PROXY = "http://127.0.0.1:9"
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
SUPPORT_ENV, REKORDBOX_ENV = library.SUPPORT_ENV, "DISCJOCKEY_REKORDBOX"


class Refused(Exception):
    """The rehearsal can't run safely: nothing was done."""


# --- safety ---

def check_work(work: Path) -> Path:
    """The work folder, resolved: outside the repo, and new or empty (nothing of anyone's lives in it)."""
    work = work.resolve()
    if work == REPO or REPO in work.parents or work in REPO.parents:
        raise Refused("The work folder must lie outside the repo.")
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        raise Refused("The work folder must be new or empty: it is deleted afterwards.")
    return work


def env_for(work: Path) -> dict[str, str]:
    """The environment every child process runs with: both overrides inside `work`; Refused when one is not."""
    env = dict(os.environ, **{SUPPORT_ENV: str(work / "support"), REKORDBOX_ENV: str(work / "rb")})
    for name in (SUPPORT_ENV, REKORDBOX_ENV):
        value = env.get(name, "")
        if not value or not Path(value).resolve().is_relative_to(work):
            raise Refused(f"{name} is not set inside the work folder.")
    env.update({name: DEAD_PROXY for name in PROXY_VARS})  # a request that slipped through fails instead of reaching a service
    return env


# --- running things ---

class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
        return bool(ok)

    def skip(self, name: str, reason: str) -> None:
        self.items.append({"check": name, "result": "SKIP", "detail": reason})
        print(f"SKIP  {name}: {reason}")

    def count(self, result: str) -> int:
        return sum(1 for i in self.items if i["result"] == result)


class Run:
    """One rehearsal: the work folder, its scratch library and the checks."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.paths = Paths(work / "music", support=work / "support")
        self.checks = Checks()
        self.n = 0

    def cli(self, tag: str, *args: str) -> tuple[int, dict]:
        """`bin/discjockey <args> --json`: the exit code and the JSON answer ({} when there is none)."""
        self.n += 1
        cmd = [str(REPO / "bin" / "discjockey"), *args, "--json"]
        print(f"  run: discjockey {' '.join(args)} --json")
        r = subprocess.run(cmd, cwd=REPO, env=env_for(self.work), capture_output=True, text=True)
        (self.work / f"cli-{self.n:02d}-{tag}.txt").write_text(f"$ {' '.join(cmd)}\n{r.stdout}\n--- stderr ---\n{r.stderr}",
                                                              encoding="utf-8")
        begin = r.stdout.find('{"v"')
        try:
            data = json.loads(r.stdout[begin:]) if begin >= 0 else {}
        except ValueError:
            data = {}
        return r.returncode, data

    def helper(self, *args: str) -> str:
        """`scripts/make_upgrade_test.py <args>`; its output, ValueError (as Refused) when it fails."""
        print(f"  run: make_upgrade_test.py {' '.join(args)}")
        r = subprocess.run([sys.executable, str(REPO / "scripts" / "make_upgrade_test.py"), *args], cwd=REPO,
                           env=env_for(self.work), capture_output=True, text=True)
        if r.returncode:
            raise Refused(f"make_upgrade_test.py {' '.join(args)} failed: {(r.stdout + r.stderr).strip()[-300:]}")
        return r.stdout

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        return self.checks.add(name, ok, detail)

    # --- reading the scratch library ---

    def state(self) -> dict:
        return library.load_state(self.paths)

    def import_waiting(self) -> int:
        """Files of the watched folders still to import (`folder list` is not built: the scratch library.db, read-only)."""
        con = sqlite3.connect(f"file:{self.paths.db_file}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM files WHERE import_state IN ('new', 'identified', 'unreadable')"
                               ).fetchone()[0]
        finally:
            con.close()

    def plan_acquires(self, songs: dict[str, dict]) -> dict[str, list[str]]:
        """The sync's plan (`planner.plan`) on a playlist made up from `songs` ({key: entry}), against the stored
        records: {song key: the reasons of its acquire actions}. (`sync plan` is not built in the command line.)"""
        state = self.state()
        tracks = [SourceTrack(k, e["title"], (e["artist"],), "Rehearsal Album", None, e["duration_ms"], None)
                  for k, e in sorted(songs.items())]
        fetched = [FetchedPlaylist(PlaylistLine(FOLDER, "rehearsal-playlist", 1), tracks, [])]
        plan = planner.plan(fetched, state, state["files"], date.today())
        out: dict[str, list[str]] = {k: [] for k in songs}
        for a in plan.actions:
            if a.kind == "acquire" and a.track_id in out:
                out[a.track_id].append(a.reason)
        return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def get(d: dict, *path, default=None):
    """`d[path[0]][path[1]]...` without a KeyError or a TypeError: `default` where a step is missing."""
    for step in path:
        try:
            d = d[step]
        except (KeyError, IndexError, TypeError):
            return default
    return d


def track_of(run: Run, tag: str, ref: str) -> tuple[int, dict]:
    code, env = run.cli(tag, "track", "show", ref)
    return code, get(env, "data", "track", default={}) or {}


# --- seeding a playlist song (as the tests do: the engine's own state functions) ---

def seed_playlist_song(run: Run, key: str, bpm: int, subfolder: str, status: str, parked: bool) -> tuple[dict, Path]:
    """A click MP3 as a playlist song's file in `Library/Rehearsal/<subfolder>`; `parked`: with its lossless upgrade
    parked in `Upgrades ready/_Upgrade test/` (else that file is deleted). Returns the entry and the file."""
    stage = run.work / f"stage-{bpm}"
    run.helper("--click", "mp3", "--bpm", str(bpm), "--into", str(stage))
    [made] = sorted(stage.glob("*.mp3"))
    target = run.paths.root / "Library" / FOLDER / subfolder / made.name
    move(made, target)
    parked_file = run.paths.root / PARKED_DIR / f"{made.stem}.aiff"
    facts = audio.file_facts(target)
    artist, title = facts.tags["artist"], facts.tags["title"]
    now = datetime.now()
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, duration_ms=40000, folder=FOLDER,
             path=target.relative_to(run.paths.root).as_posix(), status=status,
             source="qobuz" if status == "lossless" else "youtube", source_id="rehearsal", source_format="mp3",
             rejected_sources=[], in_playlists=True, added=now.isoformat(timespec="seconds"),
             upgrade=None)
    if parked:
        e["upgrade"] = {"file": parked_file.relative_to(run.paths.root).as_posix(), "source": "qobuz",
                        "source_id": "rehearsal", "source_format": "flac", "found": now.date().isoformat(),
                        "alignment": None}
    else:
        parked_file.unlink(missing_ok=True)
    with library.run_lock(run.paths.lock):
        state = library.load_state(run.paths)
        state["tracks"][key] = e
        library.save_state(run.paths, state)
        if parked:
            state = library.load_state(run.paths)
            state["tracks"][key]["upgrade"]["alignment"] = upgrades.check(run.paths, state, key).to_dict()
            library.save_state(run.paths, state)
    shutil.rmtree(stage, ignore_errors=True)
    return run.state()["tracks"][key], target


# --- the steps ---

def step1_setup(run: Run) -> tuple[str, Path]:
    """The scratch library and K's click file: returns K's key and file."""
    work, paths = run.work, run.paths
    for d in ("music", "crate", "away", "rb"):
        (work / d).mkdir(parents=True, exist_ok=True)
    library.write_music_folder(paths.support, paths.root)
    paths.data.mkdir(parents=True, exist_ok=True)
    library.save_state(paths, {**library.empty_state(), "version": 2})
    run.helper("--click", "mp3", "--into", str(work / "crate"))
    [click] = sorted((work / "crate").glob("*.mp3"))
    code, env = run.cli("folder-add", "folder", "add", str(work / "crate"))
    run.add("step 1: folder add imports the click file as an own song",
            code == 0 and get(env, "outcome") == "ok" and get(env, "data", "own_songs") == 1,
            f"exit {code}, {get(env, 'message')}")
    run.helper("--attach-upgrades", "--into", str(work / "crate"))
    code, t = track_of(run, "show", str(click))
    key = t.get("track_id", "")
    run.add("step 1: track show gives the song's key and a parked upgrade",
            code == 0 and bool(key) and bool(get(t, "upgrade", "file")) and t.get("file_state") == "here",
            f"key {key}, upgrade {get(t, 'upgrade', 'file')}, file_state {t.get('file_state')}")
    return key, click


def step2_own_song_gone(run: Run, key: str, click: Path) -> Path:
    away = run.work / "away" / click.name
    move(click, away)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 2: library scan counts the moved file as missing",
            code == 0 and get(env, "data", "missing") == 1 and get(env, "data", "back") == 0,
            f"data {get(env, 'data')}")
    code, env = run.cli("list", "missing", "list")
    items = [i for g in get(env, "data", "groups", default=[]) for i in g["items"]]
    run.add("step 2: missing list holds that one song with the action Remove",
            code == 0 and [i["track_id"] for i in items] == [key] and get(items, 0, "missing", "action") == "remove",
            f"{[(i['track_id'], get(i, 'missing', 'action')) for i in items]}")
    code, t = track_of(run, "show", key)
    run.add("step 2: track show says since when it is missing and keeps the parked upgrade",
            code == 0 and bool(get(t, "missing", "since")) and t.get("file_state") == "file_missing"
            and bool(get(t, "upgrade", "file")), f"missing {get(t, 'missing', 'since')}, file_state {t.get('file_state')}")
    return away


def step3_back(run: Run, key: str, away: Path) -> Path:
    back = run.work / "crate" / "sub" / "renamed.mp3"
    move(away, back)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 3: library scan finds it again (back 1)",
            code == 0 and get(env, "data", "back") == 1 and get(env, "data", "missing") == 0,
            f"data {get(env, 'data')}")
    code, t = track_of(run, "show", key)
    run.add("step 3: track show gives the same key at the new path, upgrade still parked",
            code == 0 and t.get("track_id") == key and t.get("path") == str(back) and not t.get("missing")
            and t.get("file_state") == "here" and bool(get(t, "upgrade", "file")),
            f"path {t.get('path')}, upgrade {get(t, 'upgrade', 'file')}")
    run.checks.skip("step 3: `folder list` shows nothing waiting to import",
                    "folder list is not built in the command line: read from the scratch library.db below")
    waiting = run.import_waiting()
    run.add("step 3: nothing waits to import (the scratch library.db)", waiting == 0, f"{waiting} file(s) waiting")
    code, env = run.cli("list", "missing", "list")
    run.add("step 3: missing list is empty",
            code == 0 and get(env, "data", "groups") == [] and get(env, "data", "empty") == "nothing_here",
            f"groups {get(env, 'data', 'groups')}")
    return back


def step4_download_again(run: Run) -> None:
    e, file = seed_playlist_song(run, SONG_4, 124, "", "lossless", parked=False)
    songs = {SONG_4: e}
    code, env = run.cli("sync-plan", "sync", "plan")
    run.checks.skip("step 4: `sync plan` plans from the stored playlist read",
                    f"not built in the command line ({get(env, 'message')}); the plan is made with planner.plan on a "
                    "playlist made up from the stored songs")
    run.add("step 4: the plan holds no acquire while the file is there", run.plan_acquires(songs)[SONG_4] == [],
            f"{run.plan_acquires(songs)}")
    away = run.work / "away" / file.name
    move(file, away)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 4: library scan counts the playlist song's file as missing",
            code == 0 and get(env, "data", "missing") == 1, f"data {get(env, 'data')}")
    acquires = run.plan_acquires(songs)[SONG_4]
    run.add("step 4: the plan holds no acquire for the missing song", acquires == [], f"{acquires}")
    code, env = run.cli("download-dry", "missing", "download", SONG_4, "--dry-run")
    run.add("step 4: missing download --dry-run says n: 1, Download again",
            code == 0 and get(env, "data", "n") == 1 and get(env, "data", "action") == "download_again",
            f"data n {get(env, 'data', 'n')}, action {get(env, 'data', 'action')}")
    code, env = run.cli("download", "missing", "download", SONG_4)
    run.add("step 4: missing download is done", code == 0 and get(env, "data", "done") == [SONG_4],
            f"exit {code}, {get(env, 'message')}")
    acquires = run.plan_acquires(songs)[SONG_4]
    run.add("step 4: the plan now holds acquire redownload", acquires == ["redownload"], f"{acquires}")
    move(away, file)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 4: library scan finds the file again (back 1)",
            code == 0 and get(env, "data", "back") == 1 and get(env, "data", "missing") == 0, f"data {get(env, 'data')}")
    acquires = run.plan_acquires(songs)[SONG_4]
    gone = run.state()["tracks"][SONG_4].get("file_gone")
    run.add("step 4: the plan holds no acquire and file_gone is cleared", acquires == [] and not gone,
            f"acquire {acquires}, file_gone {gone}")


def step5_remove(run: Run, key: str, back: Path) -> None:
    parked = run.paths.root / PARKED_DIR
    parked_files = tree(parked) if parked.exists() else []
    away = run.work / "away" / back.name
    move(back, away)
    away_sha = sha256(away)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 5: library scan counts the own file as missing again",
            code == 0 and get(env, "data", "missing") == 1, f"data {get(env, 'data')}")
    code, env = run.cli("remove-dry", "missing", "remove", key, "--dry-run")
    run.add("step 5: missing remove --dry-run says n: 1 and upgrade_waiting",
            code == 0 and get(env, "data", "n") == 1 and get(env, "data", "items", 0, "upgrade_waiting") is True,
            f"n {get(env, 'data', 'n')}, items {get(env, 'data', 'items')}")
    before = (tree(run.paths.root), run.state()["tracks"].get(key))
    code, env = run.cli("remove-no-yes", "missing", "remove", key)
    after = (tree(run.paths.root), run.state()["tracks"].get(key))
    run.add("step 5: missing remove without --yes is refused (needs_yes) and changes nothing",
            code == REFUSED and get(env, "outcome") == "refused" and get(env, "reason") == "needs_yes" and before == after,
            f"exit {code}, {get(env, 'outcome')}/{get(env, 'reason')}, unchanged {before == after}")
    code, env = run.cli("remove", "missing", "remove", key, "--yes")
    run.add("step 5: missing remove --yes is done", code == 0 and get(env, "data", "done") == [key],
            f"exit {code}, {get(env, 'message')}")
    code, t = track_of(run, "show-gone", key)
    run.add("step 5: track show no longer finds the song", code != 0 and not t, f"exit {code}")
    left = [p for p in parked_files if (parked / p).exists()]
    run.add("step 5: its parked file is gone from Upgrades ready", bool(parked_files) and not left,
            f"was {parked_files}, left {left}")
    run.add("step 5: the click file in away/ is untouched", away.is_file() and sha256(away) == away_sha, str(away.name))


def step6_placement(run: Run) -> None:
    code, env = run.cli("switch-off", "settings", "set", "auto-upgrade", "off")
    run.add("step 6: the Auto-upgrade switch is off", code == 0, f"exit {code}, {get(env, 'message')}")
    e, file = seed_playlist_song(run, SONG_6, 128, "not_lossless", "not_lossless", parked=True)
    parked_rel = e["upgrade"]["file"]
    parked_file = run.paths.root / parked_rel
    songs = {SONG_6: e}
    away = run.work / "away" / file.name
    move(file, away)
    code, env = run.cli("scan", "library", "scan")
    run.add("step 6: library scan counts the song's file as missing",
            code == 0 and get(env, "data", "missing") == 1, f"data {get(env, 'data')}")
    code, env = run.cli("download-dry", "missing", "download", SONG_6, "--dry-run")
    item = get(env, "data", "items", 0, default={})
    run.add("step 6: the dry run says the parked version is waiting and nothing is downloaded",
            code == 0 and item.get("upgrade_waiting") is True and "download" in str(get(env, "data", "words", default="")),
            f"item {item}, words {get(env, 'data', 'words')}")
    code, env = run.cli("download", "missing", "download", SONG_6)
    run.add("step 6: missing download is done", code == 0 and get(env, "data", "done") == [SONG_6],
            f"exit {code}, {get(env, 'message')}")
    acquires = run.plan_acquires(songs)[SONG_6]
    run.add("step 6: the plan holds no acquire for it", acquires == [], f"{acquires}")
    if process.running():
        run.checks.skip("step 6: sync run --auto-upgrade-only places the parked version",
                        "rekordbox is running on this machine: the phase would refuse; quit it and run again")
        return
    code, env = run.cli("phase", "sync", "run", "--auto-upgrade-only")
    block = get(env, "data", "auto_upgrade", default={})
    rows = block.get("results") or []
    run.add("step 6: sync run --auto-upgrade-only gives one done place row",
            code == 0 and len(rows) == 1 and rows[0].get("state") == "done" and rows[0].get("action") == "place",
            f"exit {code}, {get(env, 'outcome')}/{get(env, 'reason')}, rows {rows}")
    code, t = track_of(run, "show-placed", SONG_6)
    expected = f"Library/{FOLDER}/{e['artist']} - {e['title']}.aiff"
    path = get(t, "path", default="")
    run.add("step 6: track show gives the same key at Library/Rehearsal/<Artist - Title>.aiff, no upgrade",
            code == 0 and t.get("track_id") == SONG_6 and str(path).endswith(expected) and not t.get("upgrade"),
            f"path {path}, upgrade {t.get('upgrade')}")
    code, env = run.cli("checks", "check", "list")  # `track show` carries no check: `check list` is where it shows
    rows = [i for g in get(env, "data", "groups", default=[]) for i in g["items"]]
    reasons = {i["track_id"]: get(i, "check", "reason") for i in rows}
    run.add("step 6: check list holds the song with the check placed_missing",
            code == 0 and reasons == {SONG_6: "placed_missing"}, f"{reasons}")
    kept = sorted(p for p in (run.paths.root / ".discjockey" / "undo").rglob(parked_file.name)) if \
        (run.paths.root / ".discjockey" / "undo").exists() else []
    run.add("step 6: the parked file left Upgrades ready and is kept in .discjockey/undo/",
            not parked_file.exists() and bool(kept), f"parked there: {parked_file.exists()}, undo copies: {len(kept)}")
    code, env = run.cli("undo", "track", "undo", SONG_6, "--yes")
    code2, t = track_of(run, "show-undone", SONG_6)
    run.add("step 6: track undo makes the song missing again and puts the parked file back",
            code == 0 and code2 == 0 and t.get("file_state") == "file_missing" and parked_file.is_file()
            and bool(get(t, "upgrade", "file")),
            f"exit {code}, file_state {t.get('file_state')}, parked back {parked_file.is_file()}")
    code, env = run.cli("list", "missing", "list")
    items = [i for g in get(env, "data", "groups", default=[]) for i in g["items"]]
    run.add("step 6: missing list holds it with Download again",
            code == 0 and [(i["track_id"], get(i, "missing", "action")) for i in items] == [(SONG_6, "download_again")],
            f"{[(i['track_id'], get(i, 'missing', 'action')) for i in items]}")


def rehearse(work: Path) -> int:
    work = check_work(work)
    work.mkdir(parents=True, exist_ok=True)
    env = env_for(work)
    print(f"  {SUPPORT_ENV}={env[SUPPORT_ENV]}")
    print(f"  {REKORDBOX_ENV}={env[REKORDBOX_ENV]}")
    run = Run(work)
    start = time.monotonic()
    try:
        key, click = step1_setup(run)
        away = step2_own_song_gone(run, key, click)
        back = step3_back(run, key, away)
        step4_download_again(run)
        step5_remove(run, key, back)
        step6_placement(run)
    finally:
        (work / "report.json").write_text(json.dumps(run.checks.items, indent=1, ensure_ascii=False), encoding="utf-8")
        c = run.checks
        print(f"{c.count('PASS')} passed, {c.count('FAIL')} failed, {c.count('SKIP')} skipped "
              f"({time.monotonic() - start:.0f} s)")
    return 1 if run.checks.count("FAIL") else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rehearse issue 43's missing files end to end with the command line.")
    p.add_argument("--work", type=Path, required=True, help="a new or empty folder outside the repo (deleted afterwards)")
    args = p.parse_args(argv)
    try:
        return rehearse(args.work)
    except Refused as e:
        print(f"Refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
