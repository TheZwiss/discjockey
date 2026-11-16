"""tests/tool_memo.py answers a repeated ffprobe/ffmpeg run on the same bytes from memory and runs the real program for
anything else: a changed file, another command, another PATH, a failure."""
import subprocess

import numpy as np
import pytest

import tool_memo
from audio_helpers import music, needs_ffmpeg, write_aiff

pytestmark = needs_ffmpeg


@pytest.fixture
def spy(monkeypatch):
    runs = []
    real = tool_memo.real_run

    def counting(args, *a, **k):
        runs.append(list(args))
        return real(args, *a, **k)
    monkeypatch.setattr(tool_memo, "real_run", counting)
    monkeypatch.setattr(tool_memo, "_answers", type(tool_memo._answers)())  # a memory of this test's own
    return runs


def probe(path):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate", "-of", "json",
                           str(path)], capture_output=True, text=True)


def decode(path):
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "f32le", "-"],
                          capture_output=True)


def test_the_same_bytes_and_command_run_the_program_once_whatever_the_path(tmp_path, spy):
    a = write_aiff(tmp_path / "a.aiff", music(1, seed=3))
    b = tmp_path / "copy.aiff"
    b.write_bytes(a.read_bytes())
    spy.clear()  # the write above is a render; this is about reads
    first, second, third = probe(a), probe(a), probe(b)
    assert len(spy) == 1 and first.stdout == second.stdout == third.stdout and "pcm_s16be" in first.stdout
    one, two = decode(a), decode(b)
    assert len(spy) == 2 and one.stdout == two.stdout and len(one.stdout) > 1000


def test_a_changed_file_or_command_or_path_or_a_failure_runs_the_program_again(tmp_path, spy, monkeypatch):
    a = write_aiff(tmp_path / "a.aiff", music(1, seed=3))
    spy.clear()
    probe(a)
    write_aiff(a, music(1, seed=4))  # the same path, other bytes
    spy.clear()
    probe(a)
    assert len(spy) == 1
    subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "json", str(a)],
                   capture_output=True, text=True)  # another command
    assert len(spy) == 2
    monkeypatch.setenv("PATH", "/usr/bin:/bin:" + __import__("os").environ["PATH"])
    probe(a)
    assert len(spy) == 3
    (tmp_path / "bad.aiff").write_bytes(b"not audio")
    assert probe(tmp_path / "bad.aiff").returncode != 0 and probe(tmp_path / "bad.aiff").returncode != 0
    assert len(spy) == 5  # a failure is never remembered


def test_a_render_is_written_again_to_every_output_path_byte_for_byte(tmp_path, spy):
    src = write_aiff(tmp_path / "src.aiff", music(1, seed=5))
    spy.clear()
    outs = []
    for name in ("one.aiff", "two.aiff"):
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_s24be", "-f", "aiff",
                        str(out)], check=True)
        outs.append(out.read_bytes())
    assert len(spy) == 1  # one render for the two outputs
    assert outs[0] == outs[1] and len(outs[0]) > 1000
    (tmp_path / "gone").mkdir()
    (tmp_path / "gone").rmdir()
    with pytest.raises(subprocess.CalledProcessError):  # an output folder that is not there is ffmpeg's own error
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_s24be", "-f", "aiff",
                        str(tmp_path / "gone" / "x.aiff")], check=True, capture_output=True)
