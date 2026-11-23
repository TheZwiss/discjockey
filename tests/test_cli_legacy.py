"""`setup` and `update`, the two words of the old command line that are left (`cli/legacy.py`; V4.8b and V4.7b remove
them). The sync that used to run beside them is `sync run`: tests/test_cli_sync.py, test_cli_sync_phase.py."""
import pytest

import discjockey.cli.legacy as cli
from hub_helpers import choose_music

from discjockey import REPO, config, library
from discjockey.sources import spotify
from discjockey.library import Paths, run_lock
from discjockey.settings import Settings, save_settings
from discjockey.setup_cmd import TEMPLATE


@pytest.fixture
def root(tmp_path, monkeypatch):
    choose_music(tmp_path, monkeypatch)
    return tmp_path


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


def test_without_a_music_folder_the_console_says_where_to_choose_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    for command in (["update"],):
        assert cli.main(command) == 2
        assert cli.NOT_CHOSEN_TEXT in capsys.readouterr().out
    assert not (tmp_path / "support" / "config.json").exists()


def test_a_missing_music_folder_changes_nothing(tmp_path, monkeypatch, capsys):
    from discjockey import library
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    library.write_music_folder(tmp_path / "support", tmp_path / "unplugged")
    for command in (["update"], ["setup"]):
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
    assert "Spotify, Qobuz, SoundCloud or YouTube Music" in text and "open.qobuz.com/playlist" in text
    assert "soundcloud.com/some-label/sets" in text and "music.youtube.com/playlist" in text


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


def test_setup_with_a_broken_settings_file_says_so(root, monkeypatch, capsys):
    from discjockey import setup_cmd

    paths = Paths(root, support=root / ".support")
    paths.settings_file.write_text("{ not json")
    monkeypatch.setattr(setup_cmd, "check_tools", lambda: [])
    monkeypatch.setattr(setup_cmd, "_ask_client_id", lambda p: "")
    assert setup_cmd.run_setup(paths) == 2
    assert "settings.json" in capsys.readouterr().out


# --- the parser of the words not rebuilt yet (`rekordbox status | preview` and `batch list | show` are the new
# command line's: tests/test_cli_frame.py, test_cli_rekordbox.py, test_cli_batches.py) ---


def test_the_legacy_words_still_parse():
    for argv in (["setup"], ["update"]):
        assert cli.parse_args(argv).command == argv[0]
    with pytest.raises(SystemExit):  # `convert` and `rename` are `aiff convert` and `aiff rename` of the new line
        cli.parse_args(["convert", "--all", "lossless"])


def test_the_sync_flags_went_with_the_bare_sync_and_one_word_is_needed(capsys):
    for argv in ([], ["--dry-run"], ["--yes", "update"], ["update", "--yes"], ["--limit", "3", "setup"],
                 ["--json", "setup"], ["update", "--json"]):
        with pytest.raises(SystemExit) as e:
            cli.parse_args(argv)
        assert e.value.code == 2, argv
    capsys.readouterr()


def test_the_old_parser_has_no_word_of_the_removed_commands(capsys):
    """`upgrades`, `upgrade`, `batch` and `rekordbox` left with group 1.12 (the new parser answers them: tests/test_cli_batch_write.py)."""
    for argv in (["upgrades"], ["upgrade", "apply"], ["batch", "resume", "1"], ["rekordbox", "backups"]):
        with pytest.raises(SystemExit) as e:
            cli.parse_args(argv)
        assert e.value.code == 2, argv
    capsys.readouterr()


def test_hub_is_no_legacy_word_any_more(capsys):
    with pytest.raises(SystemExit):
        cli.parse_args(["hub"])
    import discjockey.cli as the_command_line
    assert the_command_line.main(["hub"]) == 2 and "hub is not a command" in capsys.readouterr().err


def test_a_busy_support_lock_in_the_terminals_update_is_a_busy_answer_not_a_traceback(root, capsys, monkeypatch):
    """The legacy `update` prints the busy words (exit 3), no traceback."""
    from discjockey import tool_updates

    def busy(support):
        raise library.SupportBusy()

    monkeypatch.setattr(tool_updates, "update", busy)
    assert cli.main(["update"]) == 3  # the terminal's update: busy words, no traceback
    out = capsys.readouterr()
    assert "Another Discjockey process" in out.out and "Traceback" not in out.out + out.err


@pytest.mark.parametrize("method", ["update_tools", "rollback_tools"])
def test_the_terminals_update_is_busy_while_a_tools_job_runs_in_the_registry(root, monkeypatch, capsys, method):
    """`tools update` is not built yet, so the legacy `update` is the terminal's only way to it: it goes through the
    same refusal `HubApi._support_job` gives (a tools job of this support folder already running, in any process)."""
    from discjockey import setup_cmd
    from discjockey.hub import registry
    monkeypatch.setattr(setup_cmd, "run_update", lambda *a: pytest.fail("must not run beside a tools job"))
    files = registry.Registry(root / ".support").create(method, "x", {}, "terminal", {})
    files.update(status="running")
    files.flush()
    try:
        assert cli.main(["update"]) == 3
    finally:
        files.update(status="done")
        files.flush()
        files.release_claim()
    out = capsys.readouterr().out
    assert "updating the tools" in out and "Traceback" not in out
    monkeypatch.setattr(setup_cmd, "run_update", lambda *a: 0)
    assert cli.main(["update"]) == 0  # the job is over: not refused any more


@pytest.mark.shapes_unchecked  # the tools update is a stub under its real kind
def test_the_terminals_update_is_busy_while_the_windows_own_update_tools_job_runs(root, monkeypatch, capsys):
    """S8: a tools update the window started is in the registry (`via: window`) like a terminal's: the legacy `update`
    refuses beside it (`TOOLS_JOB_RUNNING`), and runs once it has ended."""
    import threading
    from hub_helpers import make_unbound_api
    from discjockey import setup_cmd, tool_updates
    running, release = threading.Event(), threading.Event()

    def update(support, **kw):
        running.set()
        release.wait(20)
        return "1", "2", False

    monkeypatch.setattr(tool_updates, "update", update)
    monkeypatch.setattr(setup_cmd, "run_update", lambda *a: pytest.fail("must not run beside a tools job"))
    api, _ = make_unbound_api(root / ".support")
    assert api.update_tools()["ok"] and running.wait(10)
    try:
        assert cli.main(["update"]) == 3
    finally:
        release.set()
        assert api._jobs.wait(10)
    assert cli.TOOLS_JOB_RUNNING in capsys.readouterr().out
    monkeypatch.setattr(setup_cmd, "run_update", lambda *a: 0)
    assert cli.main(["update"]) == 0  # the job is over: not refused any more
