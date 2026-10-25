"""A small DJ Music folder in tmp_path and fakes for everything outside the hub (no network, no window)."""
from __future__ import annotations

import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from discjockey import db, library
from discjockey.sources import qobuz as qobuz_source, spotify
from discjockey.sources.base import LoginState, SourceError
from discjockey.hub import jobs
from discjockey.hub.api import HubApi, Services
from discjockey.library import Paths, empty_state, save_state
from discjockey.models import FetchedPlaylist, PlaylistInfo, SourceTrack
from discjockey.planner import ENTRY_KEYS

ID1, ID2 = "0DiscjockeyExampleList", "3DiscjockeyExampleList"
PLAYLISTS = f"# my playlists\nHard_Bounce = https://open.spotify.com/playlist/{ID1}\n" \
            f"Powertrance = https://open.spotify.com/playlist/{ID2}\n"
LOSSY = "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff"
LOSSLESS = "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff"
PARKED = "Upgrades ready/Hard_Bounce/Armin Hermann - Get Naughty.aiff"


def track(tid, title, artist, ms=180000):
    return SourceTrack(tid, title, (artist,), "Album", f"https://i.scdn.co/image/{tid}", ms, None)


TRACKS = {ID1: [track("t1", "Gimme Gimme", "Vatoz Locoz", 156000), track("t2", "Get Naughty", "Armin Hermann", 268000),
                track("t3", "Gone Track", "Some Artist"), track("t4", "AEIOU", "Pegassi")],
          ID2: [track("t2", "Get Naughty", "Armin Hermann", 268000), track("t5", "non stop", "torbentorben")]}


def entry(**kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], rejected_sources=[], in_playlists=True, added="2026-10-13T22:15:00",
             last_attempt="2026-10-13", last_upgrade_check="2026-10-13")
    e.update(kw)
    return e


def choose_music(root: Path, monkeypatch) -> Paths:
    """<root> as the chosen music folder, as Setup leaves it: DISCJOCKEY_SUPPORT at <root>/.support and its
    config.json naming <root>. `discjockey ...` (cli.main) then resolves exactly these Paths."""
    paths = Paths(root, support=root / ".support")
    monkeypatch.setenv(library.SUPPORT_ENV, str(paths.support))
    library.write_music_folder(paths.support, root)
    return paths


def make_root(tmp_path, upgrade=False):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir(parents=True, exist_ok=True)
    paths.support.mkdir(parents=True, exist_ok=True)
    paths.playlists_file.write_text(PLAYLISTS)
    state = empty_state()
    state["tracks"]["t1"] = entry(artist="Vatoz Locoz", title="Gimme Gimme", duration_ms=156000,
                                  folder="Hard_Bounce", path=LOSSLESS, status="lossless", source="qobuz",
                                  source_id="q1", source_format="flac")
    state["tracks"]["t2"] = entry(artist="Armin Hermann", title="Get Naughty", duration_ms=268000,
                                  folder="Hard_Bounce", path=LOSSY, status="not_lossless", source="youtube",
                                  source_id="abcdefghijk", source_format="opus", cutoff_hz=16000)
    state["tracks"]["t3"] = entry(artist="Some Artist", title="Gone Track", duration_ms=180000, folder="Hard_Bounce",
                                  status="missing",
                                  last_attempt=(date.today() - timedelta(days=1)).isoformat())  # not due for a retry
    if upgrade:
        state["tracks"]["t2"]["upgrade"] = {
            "file": PARKED, "source": "qobuz", "source_id": "q2", "source_format": "flac", "found": "2026-10-18",
            "alignment": {"result": "exact", "offset_samples": 0, "offset_ms": 0.0, "drift_ms": 0.0,
                          "text": "matches exactly"}}
        write(paths, PARKED, b"parked lossless")
    write(paths, LOSSLESS, b"lossless audio")
    write(paths, LOSSY, b"lossy audio")
    write_state(paths, state)
    return paths


def write_state(paths, state):
    """The records of a test library as a writer leaves them: library.db holding `state` (shaped like state.json or
    a snapshot), made with the real file facts when there is none yet (library.save_state), else saved over it."""
    paths.data.mkdir(parents=True, exist_ok=True)
    save_state(paths, {**state, "version": 2})


def records(state):
    """A state as library.db keeps it: without the read-only keys a snapshot adds (plan library stage 1, I2), so a
    test can compare what was saved with the state in memory."""
    out = {k: v for k, v in state.items() if k not in ("files", "ambiguous")}
    out["tracks"] = {key: {k: v for k, v in e.items()
                           if k not in db.READ_ONLY and not (k == "file_gone" and v is None)}
                     for key, e in state["tracks"].items()}
    return out


def write(paths, rel, data):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def finished(self, job_id=None):
        done = [e for e in self.events if isinstance(e, jobs.JobFinished) and job_id in (None, e.job_id)]
        return done[-1] if done else None


def fake_spotify(monkeypatch, tracks=None):
    tracks = tracks if tracks is not None else TRACKS
    monkeypatch.setattr(spotify, "load_session", lambda p: spotify.Session("cid", p.spotify_token, {}))
    monkeypatch.setattr(spotify, "login_state", lambda p: LoginState("ok"))
    monkeypatch.setattr(spotify, "fetch_playlist",
                        lambda s, line: FetchedPlaylist(line, list(tracks.get(line.playlist_id, [])), []))
    monkeypatch.setattr(spotify, "current_user", lambda s: ("dj1", "DJ One"))
    monkeypatch.setattr(spotify, "playlist_info", lambda s, pid, me: PlaylistInfo(
        "spotify", pid, f"Name of {pid[:4]}", "dj1", "DJ One", False, None, len(tracks.get(pid, [])), True, True))


QOBUZ_ID = "900000001"
QOBUZ_LINK = f"https://open.qobuz.com/playlist/{QOBUZ_ID}"
QOBUZ_UNREADABLE = "Qobuz doesn't show this playlist. It must be public or one of yours. Check the link."


def qobuz_track(tid, title, artist, ms=180000):
    return SourceTrack(tid, title, (artist,), "Example Album", None, ms, None, service="qobuz")


class FakeQobuzReader:
    """What sources.qobuz.open hands out in tests: no login, no network."""

    def __init__(self, tracks, unreadable, close_fails=False):
        self.tracks, self.unreadable, self.close_fails = tracks, unreadable, close_fails

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.close_fails:
            raise RuntimeError("the session was already gone")

    def info(self, playlist_id):
        if self.unreadable:
            raise SourceError(QOBUZ_UNREADABLE, "playlist_unreadable", "qobuz")
        return PlaylistInfo("qobuz", playlist_id, "Example Playlist", "7", "Example Curator", False, None,
                            len(self.tracks), False, True)

    def fetch(self, line):
        if self.unreadable:
            raise SourceError(f"playlists.txt line {line.line_no} ({line.folder}): Qobuz doesn't show this playlist.",
                              "playlist_unreadable", "qobuz")
        return FetchedPlaylist(line, list(self.tracks), [])


def fake_qobuz(monkeypatch, tracks=None, *, connected=True, unreadable=False, open_error=None, close_fails=False):
    """Qobuz as a playlist source: a login that is there (or not) and a reader over `tracks` (or one that says
    the playlist isn't shown). `open_error`: the SourceError opening the reader raises (a login Qobuz refuses, Qobuz
    not answering); `close_fails`: closing the reader raises."""
    tracks = tracks if tracks is not None else [qobuz_track("900100001", "Example Song", "Example Artist")]
    monkeypatch.setattr(qobuz_source, "login_state", lambda p: LoginState("ok") if connected else
                        LoginState("missing", qobuz_source.NOT_SET_UP))

    def open_reader(paths, token):
        if open_error is not None:
            raise open_error
        return FakeQobuzReader(tracks, unreadable, close_fails)

    monkeypatch.setattr(qobuz_source, "open", open_reader)


def services(**kw):
    calls = {"open_url": [], "open_path": [], "reveal": [], "open_in": []}
    s = Services(open_qobuz=lambda p: None, fallback=lambda **k: None,
                 open_url=calls["open_url"].append, open_path=calls["open_path"].append,
                 reveal=calls["reveal"].append, which=lambda tool: f"/opt/homebrew/bin/{tool}",
                 now=lambda: __import__("datetime").datetime(2026, 10, 20, 21, 47),
                 home=Path("/nonexistent-home"),  # never the real browsers
                 open_in=lambda browser, url, profile=None: calls["open_in"].append((browser, url, profile)))
    for k, v in kw.items():
        setattr(s, k, v)
    s.calls = calls
    return s


def make_api(paths, **kw):
    """A hub bound to `paths` without its background services (no console watch, no Spotify read)."""
    rec = Recorder()
    api = HubApi(paths.support, rec, services(**kw))
    api._attach(paths)
    api._jobs.keep_awake = _no_awake
    return api, rec


def make_unbound_api(support, **kw):
    """A hub with no music folder yet (Setup's first step)."""
    rec = Recorder()
    api = HubApi(support, rec, services(**kw))
    api._jobs.keep_awake = _no_awake
    return api, rec


class _NoAwake:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _no_awake(reason):
    return _NoAwake()


def wait_job(api, rec, answer, timeout=10):
    """Waits for the job a bridge call started; returns its JobFinished."""
    assert answer["ok"], answer
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = rec.finished(answer["job_id"])
        if f is not None:
            return f
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


def refreshed(api, rec):
    f = wait_job(api, rec, api.refresh())
    assert f.ok, f
    return f


def thread_names():
    return threading.current_thread().name


# --- the import of the user's own music (plan library stage 4): files and readers that need no ffmpeg ---

class ImportFakes:
    """Stand-ins for the import's slow readers: every file is a lossless AIFF of 200 s with full sound, tagged
    "Example Artist" and the title of its file name ("Example Artist - Song 1.aiff" -> "Song 1"), unless `tags`
    (file name -> tag dict) says otherwise. `on_probe(n)` runs before the n-th file is read (a test's gate or Stop)."""

    def __init__(self):
        self.tags: dict[str, dict] = {}
        self.seconds: dict[str, float] = {}  # file name -> its length (default 200 s)
        self.probed: list[str] = []
        self.on_probe = None

    def read_tags(self, path):
        base = {"artist": "Example Artist", "title": path.stem.split(" - ", 1)[-1], "album": None, "isrc": None}
        return {**base, **self.tags.get(path.name, {})}

    def probe(self, path):
        from discjockey.quality import AudioInfo
        self.probed.append(path.name)
        if self.on_probe:
            self.on_probe(len(self.probed))
        return AudioInfo("pcm_s16be", 44100, self.seconds.get(path.name, 200.0))

    def inspect(self, path):
        return "pcm_s16be", None


def fake_import(monkeypatch) -> ImportFakes:
    """importer.run_import with ImportFakes' readers, wherever the hub calls it."""
    from discjockey import importer
    fakes, real = ImportFakes(), importer.run_import
    monkeypatch.setattr(importer, "run_import", lambda paths, **kw: real(
        paths, read_tags=fakes.read_tags, probe=fakes.probe, inspect=fakes.inspect, **kw))
    return fakes


def import_folder(tmp_path, n=3, name="Example Drive/Music") -> Path:
    """A folder outside the music folder with n audio files ("Example Artist - Song <i>.aiff")."""
    folder = tmp_path / "outside" / name
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (folder / f"Example Artist - Song {i}.aiff").write_bytes(f"audio {i}".encode() * 50)
    return folder


def music_root(tmp_path, **kw) -> Paths:
    """make_root in a `music` folder of tmp_path, so folders beside it can be watched."""
    (tmp_path / "music").mkdir(exist_ok=True)
    return make_root(tmp_path / "music", **kw)
