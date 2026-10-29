"""Records what the hub window receives during a sync (the JSON passed to `dj.onEvent`), for the window's tests.

    uv run python scripts/record_hub_events.py            # writes tests/fixtures/hub_events_*.jsonl and the schema

The run uses the real engine and the real hub (HubApi, jobs, run.prepare/execute, Acquirer, make_ready with ffmpeg,
the real Pacer with its countdowns) in a throw-away folder. Only the outside world is faked: Spotify answers from a
list, Qobuz and YouTube "download" files made here with ffmpeg, and the pauses don't really wait. No network.
Needs ffmpeg. Two recordings: a whole sync, and one stopped by "Stop safely" during the third action.
"""
from __future__ import annotations

import dataclasses
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import types
import typing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discjockey import events as ev, run  # noqa: E402
from discjockey.sources import spotify  # noqa: E402
from discjockey.sources.base import LoginState  # noqa: E402
from discjockey.hub import jobs  # noqa: E402
from discjockey.hub.api import HubApi, Services  # noqa: E402
from discjockey.library import Paths, empty_state, save_state  # noqa: E402
from discjockey.models import Candidate, FetchedPlaylist, PlaylistInfo, SourceTrack  # noqa: E402
from discjockey.pacing import Pacer  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SHOWN_ROOT = "/Users/you/Music/Discjockey"
ID1, ID2 = "0DiscjockeyExampleList", "3DiscjockeyExampleList"
SECONDS = 12  # every track is this long (31 for the one with a weekly check: alignment needs 30 s)


def t(tid, artist, title, seconds=SECONDS, isrc=None):
    return SourceTrack(tid, title, (artist,), "Album", None, seconds * 1000, isrc)


GIMME = t("4uLU6hMCjMI75M1A2tKUQC", "Vatoz Locoz", "Gimme Gimme", isrc="DECE72605755")
WEEKEND = t("0VjIjW4GlUZAMYd2vXMi3b", "DJ TALLBOY", "THE WEEKEND")
NAUGHTY = t("7ouMYWpwJ422jRcDASZB7P", "Armin Hermann", "Get Naughty", 31, isrc="DEXX12600001")
GONE = t("1301WleyT98MSxVHPZCA6M", "Some Artist", "Gone Track")
NONSTOP = t("3n3Ppam7vgaVa1iaRUc9Lp", "torbentorben", "non stop")
AEIOU = t("2takcwOaAZWiXQijPHIx7B", "Pegassi", "AEIOU")
PLAYLISTS = {ID1: [GIMME, WEEKEND, NAUGHTY, GONE], ID2: [NONSTOP, AEIOU]}
NO_INTERNET = "Cannot connect to host www.qobuz.com:443 ssl:default [nodename nor servname provided, or not known]"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def noise(path: Path, seconds: int, seed: int, codec: list[str]) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:r=44100:a=0.3:seed={seed}", "-ac", "2", *codec,
           str(path))
    return path


class FakeQobuz:
    check = None

    def __init__(self, files):
        self.files = files  # Qobuz track id -> a FLAC made here

    def search(self, query, limit=10):
        if "Pegassi" in query or "AEIOU" in query:
            raise RuntimeError(NO_INTERNET)
        hits = {"DECE72605755": Candidate("qobuz", "112233", "Gimme Gimme", "Vatoz Locoz Various", SECONDS,
                                          isrc="DECE72605755"),
                "DEXX12600001": Candidate("qobuz", "445566", "Get Naughty", "Armin Hermann Various", 31,
                                          isrc="DEXX12600001")}
        return [hits[query]] if query in hits else []

    def download(self, cand, workdir, progress=None):
        return _deliver(self.files[cand.id], workdir / f"qobuz_{cand.id}.flac", progress)

    def close(self):
        pass


class FakeFallback:
    def __init__(self, files, **kw):
        self.files = files

    def search(self, track, sources=None):
        if track.id == NONSTOP.id and sources is None:
            return [Candidate("youtube_music", "nZ3pT0rB3n1", "non stop", "torbentorben - Topic", SECONDS,
                              url="https://music.youtube.com/watch?v=nZ3pT0rB3n1")], []
        return [], []

    def free_downloads(self, cands):
        return []

    def stream_kbps(self, source, source_id):
        return 131

    def download(self, cand, workdir, progress=None, section=None):
        return _deliver(self.files[cand.id], workdir / f"{cand.source}_{cand.id}.m4a", progress)


def _deliver(src: Path, dst: Path, progress) -> Path:
    """Copies a file in four parts with a short wait between them, so the progress events look like a download."""
    data = src.read_bytes()
    with open(dst, "wb") as f:
        for i in range(1, 5):
            f.write(data[(i - 1) * len(data) // 4: i * len(data) // 4])
            if progress:
                progress(f.tell(), len(data))
            time.sleep(0.27)
    return dst


def entry(track, folder, path, status, **kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], isrc=track.isrc, artist=track.first_artist, title=track.title,
             duration_ms=track.duration_ms, folder=folder, path=path, status=status, rejected_sources=[],
             in_playlists=True, added="2026-10-13T22:15:00", last_attempt="2026-10-13",
             last_upgrade_check="2026-10-01", upgrade=None, **kw)
    return e


def build(root: Path, audio: Path) -> Paths:
    paths = Paths(root, support=root.parent / "support")
    paths.data.mkdir(parents=True)
    paths.playlists_file.write_text(f"Hard_Bounce = https://open.spotify.com/playlist/{ID1}\n"
                                    f"Powertrance = https://open.spotify.com/playlist/{ID2}\n")
    weekend = "Library/Bouncy/DJ TALLBOY - THE WEEKEND.aiff"
    naughty = "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff"
    for rel, src in ((weekend, audio / "weekend.aiff"), (naughty, audio / "naughty_lossy.aiff")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, root / rel)
    state = empty_state()
    state["tracks"][WEEKEND.id] = entry(WEEKEND, "Bouncy", weekend, "lossless", source="qobuz", source_id="998877",
                                        source_format="flac")
    state["tracks"][NAUGHTY.id] = entry(NAUGHTY, "Hard_Bounce", naughty, "not_lossless", source="youtube",
                                        source_id="aBcDeFgHiJk", source_format="aac", cutoff_hz=16000)
    state["qobuz_usage"]["days"] = {"2026-10-15": 60}
    save_state(paths, state)
    return paths


def make_audio(folder: Path) -> dict[str, Path]:
    folder.mkdir()
    flac = ["-c:a", "flac"]
    aac = ["-af", "lowpass=f=16000", "-c:a", "aac", "-b:a", "128k"]
    files = {"112233": noise(folder / "gimme.flac", SECONDS, 1, flac),
             "445566": noise(folder / "naughty.flac", 31, 2, flac),
             "nZ3pT0rB3n1": noise(folder / "nonstop.m4a", SECONDS, 3, ["-af", "lowpass=f=19800", "-c:a", "aac",
                                                                       "-b:a", "256k"])}
    noise(folder / "weekend.aiff", SECONDS, 4, ["-c:a", "pcm_s16be"])
    lossy = noise(folder / "naughty.m4a", 31, 2, aac)
    ffmpeg("-i", str(lossy), "-c:a", "pcm_s16be", str(folder / "naughty_lossy.aiff"))
    return files


class Recorder:
    def __init__(self, root: Path, stop_at: int | None, api_ref: list):
        self.lines: list[str] = []
        self.root, self.stop_at, self.api_ref = str(root), stop_at, api_ref

    def emit(self, event):
        self.lines.append(jobs.event_json(event).replace(json.dumps(self.root)[1:-1], SHOWN_ROOT))
        if self.stop_at and isinstance(event, ev.ActionStarted) and event.index == self.stop_at:
            self.api_ref[0].stop()  # "Stop safely" pressed while the third action starts


def record(work: Path, stop_at: int | None = None) -> list[str]:
    audio = make_audio(work / "audio")
    paths = build(work / "Music", work / "audio")
    restore = []

    def patch(obj, name, value):
        restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def fetch(session, line):
        return FetchedPlaylist(line, list(PLAYLISTS[line.playlist_id]), [])

    patch(spotify, "load_session", lambda p: spotify.Session("cid", p.spotify_token, {}))
    patch(spotify, "login_state", lambda p: LoginState("ok"))
    patch(spotify, "fetch_playlist", fetch)
    patch(spotify, "current_user", lambda s: ("you", "You"))
    patch(spotify, "playlist_info", lambda s, pid, me: PlaylistInfo(
        "spotify", pid, "Playlist", "you", "You", False, None, len(PLAYLISTS[pid]), True, True))
    patch(run.QobuzSource, "open", classmethod(lambda cls, p: FakeQobuz(audio)))
    patch(run, "FallbackSource", lambda **kw: FakeFallback(audio, **kw))
    patch(run, "Pacer", lambda emit, token: Pacer(emit, token, sleep=lambda s: time.sleep(0.001),
                                                  rng=random.Random(7)))
    try:
        api_ref: list = []
        rec = Recorder(paths.root, stop_at, api_ref)
        api = HubApi(paths.support, rec, Services(now=lambda: __import__("datetime").datetime(2026, 10, 16, 21, 47)))
        api._attach(paths)
        api_ref.append(api)
        _wait(api, api.refresh())
        keys = [a["key"] for g in api.sync_preview()["groups"] for a in g["actions"]]
        _wait(api, api.start_sync(keys))
        return rec.lines
    finally:
        for obj, name, value in reversed(restore):
            setattr(obj, name, value)


def _wait(api, answer):
    assert answer["ok"], answer
    while api._jobs.status()["refresh_running"] or api._jobs.running():
        time.sleep(0.02)


# --- the JSON schema of every event (the window's tests check the fields against it) ---

def _schema_of(tp, defs: dict) -> dict:
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        options = [_schema_of(a, defs) for a in typing.get_args(tp) if a is not type(None)]
        null = type(None) in typing.get_args(tp)
        if len(options) == 1 and "type" in options[0] and null:
            return {**options[0], "type": [options[0]["type"], "null"]}
        return {"anyOf": options + ([{"type": "null"}] if null else [])}
    if origin is typing.Literal:
        values = list(typing.get_args(tp))
        return {"type": {str: "string", int: "integer"}[type(values[0])], "enum": values}
    if origin is tuple:
        args = typing.get_args(tp)
        item = args[0] if args else str
        return {"type": "array", "items": _schema_of(item, defs)}
    if dataclasses.is_dataclass(tp):
        if tp.__name__ not in defs:
            defs[tp.__name__] = {}
            defs[tp.__name__] = _object(tp, defs)
        return {"$ref": f"#/$defs/{tp.__name__}"}
    simple = {int: "integer", float: "number", str: "string", bool: "boolean", dict: "object"}
    return {"type": simple[tp]}


def _object(cls, defs: dict, event: bool = False) -> dict:
    hints = typing.get_type_hints(cls)
    props = {f.name: _schema_of(hints[f.name], defs) for f in dataclasses.fields(cls)}
    if event:
        props = {"type": {"const": cls.__name__}, **props}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def event_schema() -> dict:
    defs: dict = {}
    variants = {cls.__name__: _object(cls, defs, event=True) for cls in jobs.EVENT_TYPES}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Discjockey hub events",
            "description": "What window.dj.onEvent(event) receives. Made by scripts/record_hub_events.py.",
            "oneOf": [{"$ref": f"#/$defs/{name}"} for name in variants], "$defs": {**variants, **defs}}


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("This needs ffmpeg.")
        return 2
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, stop_at in (("hub_events_sync.jsonl", None), ("hub_events_stopped.jsonl", 3)):
        with tempfile.TemporaryDirectory() as tmp:
            lines = record(Path(tmp), stop_at)
        (FIXTURES / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{name}: {len(lines)} events")
    (FIXTURES / "hub_events.schema.json").write_text(json.dumps(event_schema(), indent=2) + "\n", encoding="utf-8")
    print("hub_events.schema.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
