import io

from discjockey.console import ConsolePrinter, waiting_lines
from discjockey.events import ActionFinished, ActionStarted, Message, Progress, Result, StepChanged, Waiting
from discjockey.models import Action, SourceTrack

A = Action("acquire", "t1", "Hard_Bounce", SourceTrack("t1", "Song", ("Artist",), "Al", None, 1, None), (0, 0))


def printer(verbose=False):
    out = io.StringIO()
    return ConsolePrinter(verbose, out), out


def test_action_lines():
    p, out = printer()
    p(ActionStarted(3, 12, A))
    p(ActionFinished(A, Result("new_lossless", "Hard_Bounce", "Artist", "Song", "t1", "Qobuz FLAC · verified lossless")))
    text = out.getvalue()
    assert "[3/12] Downloading [Hard_Bounce] Artist - Song\n" in text
    assert "-> lossless (Qobuz FLAC · verified lossless)\n" in text


def test_upgrade_lines_say_better_version_since_it_can_be_a_256_kbps_stream():
    u = Action("upgrade", "t1", "Hard_Bounce", SourceTrack("t1", "Song", ("Artist",), "Al", None, 1, None), (0, 0))
    p, out = printer()
    p(ActionStarted(1, 2, u))
    p(ActionFinished(u, Result("upgrade_ready", "Hard_Bounce", "Artist", "Song", "t1", "lines up")))
    p(ActionStarted(2, 2, u))
    p(ActionFinished(u, Result("checked", "Hard_Bounce", "Artist", "Song", "t1", "")))
    text = out.getvalue()
    assert "[1/2] Looking for a better version [Hard_Bounce] Artist - Song\n" in text
    assert "-> better version found, waiting for you (lines up)\n" in text
    assert "-> no better version yet" in text and "lossless" not in text


def test_progress_and_pauses_overwrite_one_line():
    p, out = printer()
    p(StepChanged("t1", "download"))
    p(Progress("t1", "download", 19_800_000, 31_000_000, "bytes"))
    p(Waiting("between", "Protection pause", 34, 40))
    p(Waiting("between", "Protection pause", 0, 40))
    text = out.getvalue()
    assert "\r    downloading 19.8 MB of 31.0 MB" in text
    assert "\r    Protection pause: 34 s" in text
    assert "\n" not in text  # nothing scrolls while waiting


def test_debug_messages_only_when_verbose():
    p, out = printer()
    p(Message("debug", "Qobuz search by ISRC: X -> 3 results"))
    assert out.getvalue() == ""
    p, out = printer(verbose=True)
    p(Message("debug", "Qobuz search by ISRC: X -> 3 results"))
    assert "Qobuz search by ISRC" in out.getvalue()


def test_info_and_warning_messages():
    p, out = printer()
    p(Message("info", "Reading your playlists..."))
    p(Message("warning", "Qobuz is paused for the rest of this run."))
    assert out.getvalue() == "Reading your playlists...\n  ! Qobuz is paused for the rest of this run.\n"


def test_tracks_that_only_wait_for_the_next_run_share_one_line():
    p, out = printer()
    for i in (1, 2, 3):
        p(ActionStarted(i, 3, A))
        p(ActionFinished(A, Result("queued", "Hard_Bounce", "Artist", "Song", "t1", "--limit reached")))
    assert out.getvalue() == "  Further downloads wait for the next run (--limit reached).\n"


def test_a_track_that_waits_after_work_was_shown_keeps_its_own_line():
    p, out = printer()
    p(ActionStarted(1, 3, A))
    p(StepChanged("t1", "search"))
    p(ActionFinished(A, Result("queued", "Hard_Bounce", "Artist", "Song", "t1", "Qobuz limit for today reached")))
    text = out.getvalue()
    assert "[1/3] Downloading [Hard_Bounce] Artist - Song\n" in text
    assert "-> waiting for the next run (Qobuz limit for today reached)\n" in text


def test_a_song_of_the_users_own_is_labelled_your_music():
    own = Action("upgrade", "local:1", "", SourceTrack("1", "Night Drive", ("Example Artist",), "", None, 1, None,
                                                       service="local"), (1, 0))
    p, out = printer()
    p(ActionStarted(1, 1, own))
    p(ActionFinished(own, Result("checked", "", "Example Artist", "Night Drive", "local:1", "")))
    assert "[1/1] Looking for a better version [your music] Example Artist - Night Drive\n" in out.getvalue()


def test_waiting_lines_only_for_counts_above_zero():
    assert waiting_lines(0, 0) == []
    assert waiting_lines(12, 0) == [
        "12 files in your watched folders wait to be imported. Open the window to import them."]
    assert waiting_lines(0, 3) == ["3 songs wait for your answer in the window (Is this the same song?)."]
    assert waiting_lines(1, 1) == [
        "1 file in your watched folders waits to be imported. Open the window to import it.",
        "1 song waits for your answer in the window (Is this the same song?)."]
