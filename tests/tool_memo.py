"""ffprobe and ffmpeg runs on a file are answered from memory when the same bytes went through the same command before
in this worker (each start of either program costs 35-50 ms, and the convert, undo, batch and upgrade tests read and
render the same few fixture files hundreds of times).

What is remembered, run with `subprocess.run`, when it exited 0:
- reads: `ffprobe ... <file>` and `ffmpeg ... -i <file> ... -` (decoded audio on stdout), unless the answer carries
  the file's name;
- renders: `ffmpeg -y ... -i <file or - with the bytes as input> ... <output file>` (the fixture builders and
  `audio.render_aiff`): the output file's bytes are stored and written to the output path again.
The key is the command line with the file paths left out, the input's bytes (a digest), the input's suffix and PATH, so
a changed file, another way of running it or another set of programs runs the real program. Nothing is stored for a
failure or a run with a timeout, a working folder or other arguments; a test that replaces `subprocess.run` gets its
own function. Each worker keeps its own memory, so no test sees another's files or any order: the same bytes and
command give the same answer whenever they are asked, and the real program runs for the first of every distinct pair in
every worker (`tests/test_tool_memo.py` pins that a changed file or command is run again)."""
from __future__ import annotations

import hashlib
import os
import subprocess
from collections import OrderedDict

import pytest

real_run = subprocess.run
MAX_BYTES = 200 << 20
_ALLOWED = {"capture_output", "text", "start_new_session", "check", "input"}
_answers: OrderedDict = OrderedDict()
_held = 0
stats = {"hit": 0, "miss": 0}
enabled = True  # off for a test marked `real_tools` (tests/conftest.py)


def _plan(args, kwargs):
    """(command with the paths left out, input path or None, input bytes or None, output path or None) when this call
    may be remembered, else None."""
    if not isinstance(args, (list, tuple)) or not args or not all(isinstance(a, (str, os.PathLike)) for a in args):
        return None
    if set(kwargs) - _ALLOWED or ("input" in kwargs and not isinstance(kwargs["input"], bytes)):
        return None
    args = [os.fspath(a) for a in args]
    if args[0] == "ffprobe" and "input" not in kwargs:
        return args[:-1] + ["\0in"], args[-1], None, None
    if args[0] != "ffmpeg" or args.count("-i") != 1 or args.index("-i") + 1 >= len(args) - 1:
        return None
    at = args.index("-i") + 1
    source = args[at]
    if source == "-":
        if "input" not in kwargs:
            return None
        source, data = None, kwargs["input"]
    else:
        if "input" in kwargs:
            return None
        data = None
    command = args[:at] + ["\0in"] + args[at + 1:]
    if args[-1] == "-" and "-y" not in args:
        return command, source, data, None
    if "-y" in args and "-f" in args and args[-1] != "-" and os.path.isdir(os.path.dirname(args[-1]) or "."):
        return command[:-1] + ["\0out"], source, data, args[-1]
    return None


def run(args, *a, **k):
    global _held
    plan = None if a or not enabled else _plan(args, k)
    if plan is None:
        return real_run(args, *a, **k)
    command, source, data, output = plan
    if source is not None:
        if not os.path.isfile(source):
            return real_run(args, *a, **k)
        with open(source, "rb") as f:
            data = f.read()
    suffix = os.path.splitext(source)[1].lower() if source else ""
    key = (tuple(command), suffix, os.path.splitext(output)[1].lower() if output else "", hashlib.blake2b(data, digest_size=16).digest(),
           tuple(sorted((n, v) for n, v in k.items() if n != "input")), os.environ.get("PATH"))
    found = _answers.get(key)
    if found is not None:
        _answers.move_to_end(key)
        stats["hit"] += 1
        stdout, stderr, written = found
        if output is not None:
            try:
                with open(output, "wb") as f:
                    f.write(written)
            except OSError:  # an output that can't be written: ffmpeg says so itself
                return real_run(args, *a, **k)
        return subprocess.CompletedProcess(args, 0, stdout, stderr)
    stats["miss"] += 1
    result = real_run(args, *a, **k)
    out = result.stdout
    if source is not None and not output:
        name = os.path.basename(source)
        if (name.encode() in out) if isinstance(out, bytes) else (name in (out or "")):
            return result
    written = b""
    if output is not None:
        try:
            with open(output, "rb") as f:
                written = f.read()
        except OSError:
            return result
    size = len(out or "") + len(written)
    if result.returncode == 0 and size < MAX_BYTES // 2:
        _answers[key] = (result.stdout, result.stderr, written)
        _held += size
        while _held > MAX_BYTES and _answers:
            _, (old_out, _, old_written) = _answers.popitem(last=False)
            _held -= len(old_out or "") + len(old_written)
    return result


@pytest.fixture(autouse=True)
def _real_tools(request):
    """`real_tools`: this test runs every ffprobe / ffmpeg for real (this module answers repeats otherwise)."""
    global enabled
    enabled = request.node.get_closest_marker("real_tools") is None
    yield
    enabled = True
