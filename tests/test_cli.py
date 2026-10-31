import json
import os
import signal

import pytest

import discjockey.cli as cli
from audio_helpers import music, write_aiff
from hub_helpers import choose_music

from discjockey import REPO, config, library, run
from discjockey.sources import spotify
from discjockey.sources.base import LoginState
from discjockey.acquire import AcquireResult, Ready
from discjockey.library import Paths, empty_state, run_lock, save_state
from discjockey.models import FetchedPlaylist, SourceTrack
from discjockey.setup_cmd import TEMPLATE

PLAYLISTS = "Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"


@pytest.fixture
def root(tmp_path, monkeypatch):
    choose_music(tmp_path, monkeypatch)
    return tmp_path


def fake_spotify(monkeypatch, tracks):
    monkeypatch.setattr(spotify, "load_session", lambda paths: spotify.Session("cid", paths.spotify_token, {}))
    monkeypatch.setattr(spotify, "login_state", lambda p: LoginState("ok"))
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(tracks), []))


def test_bad_playlists_file_exits_2(root, capsys):
    (root / "playlists.txt").write_text("Bouncy =\n")
    assert cli.main([]) == 2
    assert "line 1" in capsys.readouterr().out
    assert library.load_state(Paths(root, support=root / ".support"))["tracks"] == {}


def test_lock_held_exits_3(root):
    (root / "playlists.txt").write_text(PLAYLISTS)
    with run_lock(Paths(root, support=root / ".support").lock):
        assert cli.main([]) == 3


def test_dry_run_changes_no_music_file_and_writes_no_report(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)
    mine = root / "Library" / "Mine" / "Someone - Else.aiff"
    mine.parent.mkdir(parents=True)
    write_aiff(mine, music(1))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".discjockey" not in p.parts}
    fake_spotify(monkeypatch, [SourceTrack("t1", "Song", ("Artist",), "Al", None, 180000, None)])
    assert cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Download (new): 1" in out and "Dry run: no music files were changed and no report was written." in out
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".discjockey" not in p.parts}
    assert after == before  # no music file moved, written or added (no Superseded/, no Upgrades ready/ either)
    assert not (root / ".discjockey" / "reports").exists()
    state = library.load_state(Paths(root, support=root / ".support"))
    assert state["tracks"] == {} and state["files"] == ["Library/Mine/Someone - Else.aiff"]  # only indexed


def test_up_to_date(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, [])
    assert cli.main([]) == 0
    assert "up to date" in capsys.readouterr().out


def test_spotify_problem_exits_2(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)

    def no_session(paths):
        raise spotify.SpotifyError("Spotify is not set up yet. Run: discjockey setup")

    monkeypatch.setattr(spotify, "load_session", no_session)
    assert cli.main([]) == 2
    assert "setup" in capsys.readouterr().out


def test_answering_no_changes_nothing(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, [SourceTrack("t1", "Song", ("Artist",), "Al", None, 180000, None)])

    class FakeQobuz:
        def close(self):
            pass

    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, paths: FakeQobuz()))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main([]) == 0
    assert "Nothing changed" in capsys.readouterr().out
    assert library.load_state(Paths(root, support=root / ".support"))["tracks"] == {}


class FakeQobuzSource:
    def close(self):
        pass


class FakeAcquirer:
    """ctrl_c=True presses Ctrl-C (a real SIGINT) while the first track is 'downloading'."""

    def __init__(self, ctrl_c=0):
        self.ctrl_c = ctrl_c  # how many SIGINTs one press delivers (uv/caffeinate forward it a second time)
        self.calls = 0

    def acquire(self, track, rejected, workdir, lossless_only, tracker, exact=None, upload=None):
        self.calls += 1
        for _ in range(self.ctrl_c):
            os.kill(os.getpid(), signal.SIGINT)
        p = workdir / "qobuz_q1.aiff"
        p.write_bytes(b"audio")
        return AcquireResult("ready", Ready(p, "lossless", "qobuz", "q1", "flac", None, "Qobuz FLAC · verified lossless"))


TWO_TRACKS = [SourceTrack("t1", "Song", ("Artist",), "Al", None, 180000, None),
              SourceTrack("t2", "Other", ("Artist",), "Al", None, 180000, None)]


def full_run(root, monkeypatch, acquirer, args=("--yes",), tracks=TWO_TRACKS[:1]):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, tracks)
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, paths: FakeQobuzSource()))
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: acquirer)
    return cli.main(list(args))


def test_full_run_places_files_and_writes_report(root, monkeypatch, capsys):
    assert full_run(root, monkeypatch, FakeAcquirer()) == 0
    assert (root / "Library" / "Hard_Bounce" / "Artist - Song.aiff").read_bytes() == b"audio"
    pipeline = root / ".discjockey"
    assert sorted(p.suffix for p in (pipeline / "reports").iterdir()) == [".json", ".md"]
    assert (pipeline / "not_lossless.md").exists()
    assert list((pipeline / ".tmp").iterdir()) == []
    out = capsys.readouterr().out
    assert "[1/1] Downloading [Hard_Bounce] Artist - Song" in out and "-> lossless" in out
    assert "Qobuz today: 0 of 80 used" in out


def test_ctrl_c_finishes_the_current_track_then_stops(root, monkeypatch, capsys):
    acq = FakeAcquirer(ctrl_c=1)
    assert full_run(root, monkeypatch, acq, tracks=TWO_TRACKS) == 130
    assert acq.calls == 1  # the second track was never started
    assert (root / "Library" / "Hard_Bounce" / "Artist - Song.aiff").exists()  # the first one was finished
    pipeline = root / ".discjockey"
    assert (pipeline / "library.db").exists()
    assert len(list((pipeline / "reports").glob("*.md"))) == 1
    assert "Stopping safely" in capsys.readouterr().out
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_one_press_delivered_twice_still_stops_safely(root, monkeypatch):
    acq = FakeAcquirer(ctrl_c=2)
    assert full_run(root, monkeypatch, acq, tracks=TWO_TRACKS) == 130
    assert acq.calls == 1
    assert (root / "Library" / "Hard_Bounce" / "Artist - Song.aiff").exists()  # not killed half-way


def test_help_calls_upgrades_better_versions(capsys):
    with pytest.raises(SystemExit):
        cli.parse_args(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "upgrades: go through the better versions found for your lossy tracks" in out


def test_limit_must_be_positive(capsys):
    with pytest.raises(SystemExit):
        cli.parse_args(["--limit", "0"])


def test_extra_allows_more_today(root, monkeypatch, capsys):
    full_run(root, monkeypatch, FakeAcquirer(), args=("--yes", "--extra", "15"))
    settings = json.loads((root / ".support" / "settings.json").read_text())
    assert settings["extra_today"]["amount"] == 15
    assert "of 95 used" in capsys.readouterr().out


def test_qobuz_login_failure_is_recorded(root, monkeypatch):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, TWO_TRACKS[:1])

    def refuse(cls, paths):
        raise run.QobuzError("Qobuz did not accept your login. Run: discjockey setup")

    monkeypatch.setattr(run.QobuzSource, "open", classmethod(refuse))
    assert cli.main(["--yes"]) == 2
    state = library.load_state(Paths(root, support=root / ".support"))
    assert state["qobuz_usage"]["signals"][0]["kind"] == "login_failed"


def test_template_has_no_active_lines():
    with pytest.raises(config.ConfigError, match="no active playlists"):
        config.parse_playlists(TEMPLATE)


def test_setup_never_prints_streamrip_login_text(root, monkeypatch, capsys):
    from streamrip.exceptions import InvalidAppIdError

    from discjockey import qobuz, setup_cmd

    def broken_login(paths):
        raise InvalidAppIdError("Invalid app id from params {'email': 'dj@example.com', 'password': '5f4dcc3b'}")

    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(setup_cmd, "_ask_client_id", lambda paths: "0" * 32)
    monkeypatch.setattr(spotify, "login", lambda client_id, token_path, **kw: None)
    monkeypatch.setattr(spotify, "load_session", lambda paths: object())
    monkeypatch.setattr(spotify, "api_get", lambda session, url: {"id": "me"})
    monkeypatch.setattr(qobuz, "interactive_login", broken_login)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    assert setup_cmd.run_setup(Paths(root, support=root / ".support")) == 2
    out = capsys.readouterr().out
    assert "Qobuz login failed" in out and "5f4dcc3b" not in out and "dj@example.com" not in out


@pytest.mark.parametrize("command", ["setup", "update"])
def test_setup_and_update_wait_for_a_running_sync(root, monkeypatch, capsys, command):
    from discjockey import setup_cmd
    monkeypatch.setattr(setup_cmd, f"run_{command}", lambda *a: pytest.fail("must not run during a sync"))
    with run_lock(Paths(root, support=root / ".support").lock):
        assert cli.main([command]) == 3
    assert "still going" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["setup", "update"])
def test_setup_and_update_hold_the_lock(root, monkeypatch, command):
    from discjockey import setup_cmd

    def body(*a):  # a sync started meanwhile would have to wait
        with pytest.raises(cli.LockHeld):
            with run_lock(Paths(root, support=root / ".support").lock):
                pass
        return 0

    monkeypatch.setattr(setup_cmd, f"run_{command}", body)
    assert cli.main([command]) == 0


def test_no_keyboard_input_gives_a_plain_message(root, monkeypatch, capsys):
    from discjockey import setup_cmd

    def no_input(paths):
        raise EOFError
    monkeypatch.setattr(setup_cmd, "run_setup", no_input)
    assert cli.main(["setup"]) == 2
    assert "Terminal window" in capsys.readouterr().out


def test_setup_with_a_google_qobuz_account_shows_the_password_steps(root, monkeypatch, capsys):
    from discjockey import qobuz, setup_cmd

    logins = []
    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(setup_cmd, "_ask_client_id", lambda paths: "0" * 32)
    monkeypatch.setattr(spotify, "login", lambda client_id, token_path, **kw: None)
    monkeypatch.setattr(spotify, "load_session", lambda paths: object())
    monkeypatch.setattr(spotify, "api_get", lambda session, url: {"id": "me"})
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    monkeypatch.setattr(qobuz, "interactive_login", lambda paths: logins.append("password"))
    assert setup_cmd.run_setup(Paths(root, support=root / ".support")) == 0
    out = capsys.readouterr().out
    assert logins == ["password"]
    assert setup_cmd.QOBUZ_PASSWORD_URL in out and "Qobuz login works" in out
    assert "alias discjockey=" in out and str(REPO / "bin" / "discjockey") in out and "bin/discjockey" in out


def test_sync_says_when_lossless_versions_wait(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, TWO_TRACKS[:1])
    f = root / "Library" / "Hard_Bounce" / "not_lossless" / "Artist - Song.aiff"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"lossy")
    state = empty_state()
    state["tracks"]["t1"] = {
        "aliases": [], "isrc": None, "artist": "Artist", "title": "Song", "duration_ms": 180000,
        "folder": "Hard_Bounce", "path": "Library/Hard_Bounce/not_lossless/Artist - Song.aiff",
        "status": "not_lossless", "source": "youtube_music", "source_id": "y1", "source_format": "opus",
        "cutoff_hz": 20000, "rejected_sources": [], "in_playlists": True, "added": "2026-10-01T10:00:00",
        "last_attempt": "2026-10-01", "last_upgrade_check": "2026-10-01",
        "upgrade": {"file": "Upgrades ready/Hard_Bounce/Artist - Song.aiff", "source": "qobuz", "source_id": "q1",
                    "source_format": "flac", "found": "2026-10-01",
                    "alignment": {"result": "exact", "offset_samples": 0, "offset_ms": 0.0, "drift_ms": 0.0,
                                  "text": "matches exactly"}}}
    save_state(Paths(root, support=root / ".support"), state)
    assert cli.main([]) == 0  # nothing to do: the parked upgrade stops further checks
    out = capsys.readouterr().out
    assert "1 better version is ready: run `discjockey upgrades`." in out
    assert "Better version ready" in (root / ".discjockey" / "not_lossless.md").read_text()


def test_without_a_music_folder_the_console_says_where_to_choose_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    for command in ([], ["upgrades"], ["update"], ["--dry-run"]):
        assert cli.main(command) == 2
        assert cli.NOT_CHOSEN_TEXT in capsys.readouterr().out
    assert not (tmp_path / "support" / "config.json").exists()


def test_a_missing_music_folder_changes_nothing(tmp_path, monkeypatch, capsys):
    from discjockey import library
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    library.write_music_folder(tmp_path / "support", tmp_path / "unplugged")
    for command in ([], ["setup"]):
        assert cli.main(command) == 2
        assert "isn't there: " + str(tmp_path / "unplugged") in capsys.readouterr().out
    assert not (tmp_path / "unplugged").exists()


def test_setup_asks_for_the_music_folder_first(tmp_path, monkeypatch, capsys):
    from discjockey import library, setup_cmd
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    monkeypatch.setattr(setup_cmd, "run_setup", lambda paths: 0)
    answers = iter(["relative", str(tmp_path / "Music" / "DJ")])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["setup"]) == 0
    assert "type its full path" in capsys.readouterr().out
    assert library.read_music_folder(tmp_path / "support") == (tmp_path / "Music" / "DJ").resolve()
    assert (tmp_path / "Music" / "DJ" / ".discjockey" / ".lock").exists()  # setup ran under the lock in it


def test_setup_asks_before_using_a_folder_with_other_files(tmp_path, monkeypatch):
    from discjockey import library, setup_cmd
    other = tmp_path / "Stuff"
    other.mkdir()
    (other / "song.mp3").write_bytes(b"x")
    answers = iter([str(other), "n", str(other), "y"])
    paths = setup_cmd.ask_music_folder(tmp_path / "support", home=tmp_path / "home",
                                       ask=lambda prompt="": next(answers))
    assert paths.root == other.resolve() and library.read_music_folder(tmp_path / "support") == other.resolve()


def test_setup_checks_the_music_folder_against_the_program_folder(tmp_path, monkeypatch):
    from discjockey import setup_cmd, tools
    program = tmp_path / "Program"
    program.mkdir()
    monkeypatch.setattr(tools, "program_dir", lambda: program)
    answers = iter([str(program), str(tmp_path / "Music")])
    paths = setup_cmd.ask_music_folder(tmp_path / "support", home=tmp_path / "home",
                                       ask=lambda prompt="": next(answers))
    assert paths.root == (tmp_path / "Music").resolve()  # the program folder itself was refused


def lossless_song(key, title, rel):
    return {"aliases": [], "isrc": None, "artist": "Artist", "title": title, "duration_ms": 180000,
            "folder": "Hard_Bounce", "path": rel, "status": "lossless", "source": "qobuz", "source_id": key,
            "source_format": "flac", "cutoff_hz": None, "rejected_sources": [], "in_playlists": True,
            "added": "2026-10-01T10:00:00", "last_attempt": "2026-10-01", "last_upgrade_check": "2026-10-01"}


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("elsewhere, line", [
    (0, None),
    (1, "1 file is not where the playlist order puts it; tidy up in the window."),
    (2, "2 files are not where the playlist order puts them; tidy up in the window.")])
def test_sync_says_how_many_files_a_tidy_up_would_move(root, monkeypatch, capsys, elsewhere, line, dry_run):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, TWO_TRACKS)
    state = empty_state()
    for i, t in enumerate(TWO_TRACKS):
        rel = f"Library/{'Old' if i < elsewhere else 'Hard_Bounce'}/Artist - {t.title}.aiff"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(f"audio {t.id}".encode())
        state["tracks"][t.id] = lossless_song(t.id, t.title, rel)
    save_state(Paths(root, support=root / ".support"), state)
    assert cli.main(["--dry-run"] if dry_run else []) == 0
    out = capsys.readouterr().out
    assert ("No downloads needed." in out) is not dry_run
    tidy_lines = [s for s in out.splitlines() if "tidy up in the window" in s]
    assert tidy_lines == ([line] if line else [])


def test_sync_says_which_songs_wait_for_an_answer_in_the_window(root, monkeypatch, capsys):
    (root / "playlists.txt").write_text(PLAYLISTS)
    fake_spotify(monkeypatch, TWO_TRACKS[:1])
    rel = "Library/Mine/Another Artist - Song.aiff"  # a file of the user's own: maybe the playlist's "Song"
    (root / rel).parent.mkdir(parents=True)
    (root / rel).write_bytes(b"audio mine")
    state = empty_state()
    state["tracks"]["local:1"] = lossless_song("local:1", "Song", rel) | {
        "artist": "Another Artist", "folder": "", "in_playlists": False, "source": "manual", "source_id": None}
    save_state(Paths(root, support=root / ".support"), state)
    assert cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "1 song waits for your answer in the window (Is this the same song?)." in out
    assert not [s for s in out if "wait to be imported" in s]


def test_setup_skips_spotify_on_an_empty_client_id(root, monkeypatch, capsys):
    from discjockey import qobuz, setup_cmd
    from discjockey.settings import load_settings

    paths = Paths(root, support=root / ".support")
    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(spotify, "login", lambda *a, **k: pytest.fail("Spotify was skipped"))
    monkeypatch.setattr(qobuz, "interactive_login", lambda p: None)
    answers = iter(["", "1"])  # Enter on the Client ID, then "1" for the Qobuz login
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert setup_cmd.run_setup(paths) == 0
    assert "Spotify skipped" in capsys.readouterr().out
    assert load_settings(paths.settings_file).spotify_skipped
    text = paths.playlists_file.read_text()
    assert "Spotify or Qobuz" in text and "open.qobuz.com/playlist" in text


def test_a_client_id_connects_spotify_and_clears_the_skip(root, monkeypatch):
    from discjockey import qobuz, setup_cmd
    from discjockey.settings import Settings, load_settings, save_settings

    paths = Paths(root, support=root / ".support")
    save_settings(paths.settings_file, Settings(spotify_skipped=True))
    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(setup_cmd, "_ask_client_id", lambda p: "0" * 32)
    monkeypatch.setattr(spotify, "login", lambda client_id, token_path, **kw: None)
    monkeypatch.setattr(spotify, "load_session", lambda p: object())
    monkeypatch.setattr(spotify, "api_get", lambda session, url: {"id": "me"})
    monkeypatch.setattr(qobuz, "interactive_login", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    assert setup_cmd.run_setup(paths) == 0
    assert not load_settings(paths.settings_file).spotify_skipped


def test_a_qobuz_only_playlists_file_never_asks_for_spotify(root, monkeypatch, capsys):
    from hub_helpers import QOBUZ_LINK, fake_qobuz, qobuz_track

    (root / "playlists.txt").write_text(f"Example_Playlist = {QOBUZ_LINK}\n")
    fake_qobuz(monkeypatch, [qobuz_track("900100001", "Example Song", "Example Artist")])  # no Spotify files at all
    monkeypatch.setattr(spotify, "load_session", lambda paths: pytest.fail("Spotify was not asked for"))
    assert cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Download (new): 1" in out and "Spotify" not in out


def test_a_spotify_line_with_spotify_skipped_asks_to_set_it_up(root, monkeypatch, capsys):
    from discjockey.settings import Settings, save_settings

    (root / "playlists.txt").write_text(PLAYLISTS)
    save_settings(Paths(root, support=root / ".support").settings_file, Settings(spotify_skipped=True))
    assert cli.main(["--dry-run"]) == 2
    assert "Spotify is not set up yet. Run: discjockey setup" in capsys.readouterr().out


def test_setup_with_a_broken_settings_file_says_so(root, monkeypatch, capsys):
    from discjockey import setup_cmd

    paths = Paths(root, support=root / ".support")
    paths.settings_file.write_text("{ not json")
    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(setup_cmd, "_ask_client_id", lambda p: "")
    assert setup_cmd.run_setup(paths) == 2
    assert "settings.json" in capsys.readouterr().out
